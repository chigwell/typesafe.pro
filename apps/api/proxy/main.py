import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis
from starlette.responses import JSONResponse, Response

from .admin import admin_router
from .auth import client_ip, digest
from .config import Settings
from .content_api import content_admin_router, public_content_router
from .content_store import new_state as new_content_state
from .endpoint import ProxyEndpoint
from .endpoint import admission_policy as admission_policy
from .endpoint import retry_seconds as retry_seconds
from .limiter import Limiter
from .scheduler import BodyBudget, Scheduler
from .storage import Store
from .system import SystemSampler
from .telemetry import Telemetry

CORS_HEADERS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-expose-headers", b"X-Request-ID, Retry-After"),
]
CORS_PREFLIGHT_HEADERS = CORS_HEADERS + [
    (b"access-control-allow-methods", b"POST, OPTIONS"),
    (b"access-control-allow-headers", b"Authorization, Content-Type, X-Request-ID"),
    (b"access-control-max-age", b"600"),
    (b"cache-control", b"no-store"),
]
PUBLIC_PAGE_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")


class RequestID:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict((k.lower(), v) for k, v in scope["headers"])
        values = [v for k, v in scope["headers"] if k.lower() == b"x-request-id"]
        value = values[0] if len(values) == 1 else b""
        request_id = (
            value.decode("ascii") if re.fullmatch(rb"[A-Za-z0-9_-]{1,128}", value) else uuid4().hex
        )
        scope["request_id"] = request_id
        is_admin = scope["path"] == "/admin" or scope["path"].startswith("/admin/")
        cors = CORS_HEADERS
        preflight = CORS_PREFLIGHT_HEADERS
        if is_admin:
            origins = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"origin"]
            allowed = scope["app"].state.settings.admin_allowed_origins
            if (origins and (len(origins) != 1 or origins[0] not in allowed)) or (
                scope["method"] == "POST"
                and not origins
                and headers.get(b"sec-fetch-site") == b"cross-site"
            ):
                return await JSONResponse(
                    {"detail": "Origin not allowed"},
                    status_code=403,
                    headers={"Cache-Control": "no-store", "Vary": "Origin"},
                )(scope, receive, send)
            cors = [
                (b"vary", b"Origin"),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ]
            if origins:
                cors += [
                    (b"access-control-allow-origin", origins[0].encode("latin-1")),
                    (b"access-control-allow-credentials", b"true"),
                    (b"access-control-expose-headers", b"Retry-After, X-Request-ID"),
                ]
            preflight = cors + [
                (b"access-control-allow-methods", b"GET, POST"),
                (b"access-control-allow-headers", b"Content-Type"),
                (b"access-control-max-age", b"600"),
            ]

        if (
            scope["method"] == "OPTIONS"
            and b"origin" in headers
            and b"access-control-request-method" in headers
            and (
                is_admin
                or (
                    scope["path"] in ("/v1/systemone", "/analytics/view")
                    and headers[b"access-control-request-method"] == b"POST"
                )
            )
        ):
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": preflight + [(b"x-request-id", request_id.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def with_id(message):
            if message["type"] == "http.response.start":
                response_headers = [
                    (k, v)
                    for k, v in message["headers"]
                    if k.lower() != b"x-request-id"
                    and not k.lower().startswith(b"access-control-")
                    and not (is_admin and k.lower() in (b"cache-control", b"vary"))
                ]
                message["headers"] = (
                    response_headers + cors + [(b"x-request-id", request_id.encode())]
                )
            await send(message)

        await self.app(scope, receive, with_id)


def create_app(settings=None, transport=None, *, store=None, redis=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        state = app.state
        state.settings = config
        state.redis = redis or Redis.from_url(
            config.redis_url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
            max_connections=64,
        )
        state.store = store or await Store.connect(config.database_url)
        state.store.retention_seconds = config.observability_retention_seconds
        new_content_state(state)
        try:
            await state.redis.ping()
            await state.store.policies()
            state.limiter = Limiter(state.redis, config)
            state.scheduler = Scheduler(state.limiter, config)
            state.budget = BodyBudget(config)
            state.telemetry = Telemetry(
                state.store, state.redis, config.observability_retention_seconds
            )
            state.telemetry.start()
            state.system = SystemSampler(config)
            state.system.start()
            await state.scheduler.start()
            async with httpx.AsyncClient(
                transport=transport or httpx.AsyncHTTPTransport(retries=0),
                timeout=httpx.Timeout(connect=5, read=60, write=60, pool=5),
                limits=httpx.Limits(
                    max_connections=config.max_inflight,
                    max_keepalive_connections=config.max_inflight,
                ),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                state.client = client
                try:
                    yield
                finally:
                    await state.scheduler.close()
                    await state.telemetry.close()
                    await state.system.close()
        finally:
            if store is None:
                await state.store.close()
            if redis is None:
                await state.redis.aclose()

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
        title="typesafe.pro public content API",
        version="1",
        description="Read-only, cached access to published TypeSafe use cases.",
    )
    app.router.redirect_slashes = False
    app.add_middleware(RequestID)
    app.include_router(content_admin_router(), include_in_schema=False)
    app.include_router(admin_router(), include_in_schema=False)
    app.include_router(public_content_router())

    class AdminNotFound:
        async def __call__(self, scope, receive, send):
            await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)

    app.router.add_route("/admin", AdminNotFound(), methods=None)
    app.router.add_route("/admin/{path:path}", AdminNotFound(), methods=None)

    @app.get("/health", include_in_schema=False)
    async def health(request: Request) -> Response:
        return JSONResponse(
            {"ok": True, "service": "typesafe-proxy", "release": app.state.settings.release_sha},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/analytics/view", include_in_schema=False)
    async def analytics_view(request: Request) -> Response:
        state = request.app.state
        config = state.settings
        try:
            body = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 2048:
                        raise HTTPException(413, "Analytics request too large")
                    body.extend(chunk)
            data = json.loads(body)
            path = data.get("path") if isinstance(data, dict) else None
        except HTTPException:
            raise
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            raise HTTPException(400, "Invalid analytics request") from None
        if (
            not isinstance(path, str)
            or not path
            or len(path) > 1024
            or path != path.strip()
            or not PUBLIC_PAGE_PATH.fullmatch(path)
            or "?" in path
            or "#" in path
            or path == "/admin"
            or path.startswith("/admin/")
        ):
            raise HTTPException(400, "Path is not a public canonical path")
        ip = client_ip(request.scope, config.trusted_proxies)
        ip_hash = digest(config.hash_secret, ip.encode(), "analytics-ip")
        try:
            retry = await state.limiter.analytics_view_retry(ip_hash)
        except Exception:
            raise HTTPException(
                503, "Analytics temporarily unavailable", headers={"Retry-After": "5"}
            ) from None
        if retry:
            raise HTTPException(429, "Too many views", headers={"Retry-After": str(retry)})
        now = datetime.now(UTC)
        visitor_hash = digest(
            config.hash_secret,
            f"{now.date().isoformat()}:{ip}".encode(),
            "analytics-visitor",
        )
        try:
            await state.store.record_page_view(path, visitor_hash, now)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Analytics temporarily unavailable") from None
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    app.router.add_route("/{path:path}", ProxyEndpoint(app), methods=None)
    return app


app = create_app()
