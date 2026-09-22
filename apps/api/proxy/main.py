import asyncio
import contextlib
import json
import re
import time
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl
from uuid import uuid4

import anyio
import asyncpg
import httpx
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from .admin import admin_router
from .auth import authenticate, bearer, client_ip, digest
from .config import MAX_BODY_BYTES, Settings
from .limiter import Limiter
from .payload import CAPTURE_BYTES, estimate_tokens, inspect_response, usage_tokens, valid_response
from .scheduler import BodyBudget, Rejected, Scheduler
from .storage import Store
from .system import SystemSampler
from .telemetry import Telemetry, new_event
from .transport import ProxyResponse, upstream_request
from .validation import InvalidRequest, validate_body, validate_media, validate_route

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


def retry_seconds(upstream):
    if upstream.status_code in (401, 403):
        return 120
    value = upstream.headers.get("retry-after", "1")
    try:
        return float(value)
    except ValueError:
        try:
            return (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 1


def admission_policy(policies, tier):
    return policies["paid"] if tier == "admin" else policies[tier]


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
                    scope["path"] == "/v1/systemone"
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

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.router.redirect_slashes = False
    app.add_middleware(RequestID)
    app.include_router(admin_router())

    class AdminNotFound:
        async def __call__(self, scope, receive, send):
            await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)

    app.router.add_route("/admin", AdminNotFound(), methods=None)
    app.router.add_route("/admin/{path:path}", AdminNotFound(), methods=None)

    @app.get("/health")
    async def health(request: Request) -> Response:
        return JSONResponse(
            {"ok": True, "service": "typesafe-proxy", "release": app.state.settings.release_sha},
            headers={"Cache-Control": "no-store"},
        )

    class ProxyEndpoint:
        async def __call__(self, scope, receive, send):
            state = app.state
            config = state.settings
            started = time.monotonic()
            event = new_event(scope, scope["request_id"])
            event["client_ip"] = client_ip(scope, config.trusted_proxies)
            event["ip_hash"] = digest(config.hash_secret, event["client_ip"].encode(), "ip")
            secrets = [key.secret for key in config.masters] + list(config.legacy_tokens)
            secrets += [
                *config.admin_tokens,
                config.hash_secret,
                config.database_url,
                config.redis_url,
                config.admin_password,
            ]
            secrets += [v for _, v in parse_qsl(scope["query_string"].decode("latin-1")) if v]
            secrets.append(bearer(scope["headers"]))
            claimed = False
            body_size = 0
            stage = "admission"
            headers_sent = False
            response_complete = False
            watcher = None
            work = None

            async def tracked_send(message):
                nonlocal headers_sent, response_complete
                if message["type"] == "http.response.start":
                    headers_sent = True
                await send(message)
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    response_complete = True

            async def disconnected():
                while True:
                    if (await receive())["type"] == "http.disconnect":
                        return

            async def dispatch(body):
                queued = time.monotonic()
                master = None
                upstream_started = None
                captured = bytearray()
                truncated = False
                upstream = None

                def observe(chunk):
                    nonlocal truncated
                    available = CAPTURE_BYTES - len(captured)
                    captured.extend(chunk[:available])
                    truncated |= len(chunk) > available

                try:
                    try:
                        master, owner = await state.scheduler.acquire(policy)
                    finally:
                        event["queue_ms"] = (time.monotonic() - queued) * 1000
                    event["master_key_id"] = master.key_id
                    upstream_started = time.monotonic()
                    async with asyncio.timeout(config.request_timeout):
                        upstream = await state.client.send(
                            upstream_request(scope, body, master.secret),
                            stream=True,
                        )
                        event["upstream_status"] = event["status"] = upstream.status_code
                        if upstream.status_code >= 400:
                            event["error_code"] = "upstream_error"
                        else:
                            event["error_code"] = ""
                        if upstream.status_code in (429, 529, 401, 403):
                            await state.limiter.cooldown(master, retry_seconds(upstream))
                        # This endpoint owns the disconnect listener, including while queued.
                        response_scope = dict(scope, asgi={"version": "3.0", "spec_version": "2.4"})
                        await ProxyResponse(upstream, observe)(
                            response_scope, receive, tracked_send
                        )
                finally:
                    if upstream_started is not None:
                        event["upstream_ms"] = (time.monotonic() - upstream_started) * 1000
                    try:
                        if upstream is not None:
                            with anyio.CancelScope(shield=True):
                                await upstream.aclose()
                    finally:
                        if master is not None:
                            with anyio.CancelScope(shield=True):
                                with contextlib.suppress(RedisError, OSError):
                                    await state.scheduler.release(master, owner)
                    if upstream is not None:
                        data, raw, parse_error = inspect_response(
                            bytes(captured),
                            upstream.headers.get("content-encoding", ""),
                            truncated,
                        )
                        event["usage_tokens"] = usage_tokens(data)
                        event["response_truncated"] = truncated or raw is None
                        if scope["path"] == "/v1/systemone" and 200 <= upstream.status_code < 300:
                            questions = None
                            try:
                                payload = json.loads(body)
                                if isinstance(payload, dict) and isinstance(
                                    payload.get("questions"), dict
                                ):
                                    questions = set(payload["questions"])
                            except (ValueError, RecursionError):
                                pass
                            if raw is not None:
                                event["upstream_valid"] = valid_response(data, questions)
                                if not event["upstream_valid"]:
                                    event["error_code"] = "invalid_upstream_response"
                                    event["error_detail"] = (
                                        parse_error or "Response contract mismatch"
                                    )
                        elif upstream.status_code >= 400:
                            event["upstream_valid"] = False
                        event["raw_response"] = (
                            raw
                            if raw is not None
                            else (
                                bytes(captured).decode("utf-8", "replace")
                                if not upstream.headers.get("content-encoding")
                                else "[encoded or truncated body]"
                            )
                        )
                        event["response_truncated"] |= len(event["raw_response"].encode()) > 8192

            try:
                validate_route(scope)
                state.budget.enter()
                claimed = True
                identity = await authenticate(scope, config, state.store, state.redis)
                event.update(
                    client_tier=identity.tier,
                    client_hash=identity.client_hash,
                    ip_hash=identity.ip_hash,
                )
                policy = admission_policy(await state.store.policies(), identity.tier)
                if identity.tier != "admin":
                    retry = await state.limiter.client_retry(identity, policy)
                    if retry:
                        raise Rejected("rate_limit_exceeded", 429, retry)
                validate_media(scope["headers"])
                stage = "upload"
                body = bytearray()
                async with asyncio.timeout(60):
                    async for chunk in Request(scope, receive).stream():
                        if body_size + len(chunk) > MAX_BODY_BYTES:
                            raise Rejected("request_too_large", 413)
                        state.budget.grow(len(chunk))
                        body_size += len(chunk)
                        body.extend(chunk)
                event["request_bytes"] = body_size
                event["estimated_tokens"] = estimate_tokens(body)
                content = bytes(body)
                del body
                validate_body(content)
                stage = "dispatch"
                watcher = asyncio.create_task(disconnected())
                work = asyncio.create_task(dispatch(content))
                done, _ = await asyncio.wait((watcher, work), return_when=asyncio.FIRST_COMPLETED)
                if work in done or response_complete:
                    await work
                else:
                    work.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await work
                    raise ClientDisconnect()
            except (Exception, asyncio.CancelledError) as error:
                event["exception_class"] = type(error).__name__
                event["error_detail"] = (
                    str(error)
                    + "\n"
                    + "\n".join(
                        f"{frame.name}:{frame.lineno}"
                        for frame in traceback.extract_tb(error.__traceback__)
                    )
                )
                if isinstance(error, InvalidRequest):
                    code, status, retry = error.code, error.status, None
                    event["error_detail"] = error.code
                elif isinstance(error, Rejected):
                    code, status, retry = error.code, error.status, error.retry
                elif isinstance(error, (ClientDisconnect, asyncio.CancelledError)):
                    code, status, retry = "client_disconnected", 499, 1
                elif isinstance(error, TimeoutError) and stage == "admission":
                    code, status, retry = "limiter_unavailable", 503, 1
                elif isinstance(error, (httpx.TimeoutException, TimeoutError)):
                    code, status, retry = (
                        "upstream_timeout" if event["master_key_id"] else "request_timeout",
                        504,
                        1,
                    )
                elif isinstance(error, httpx.HTTPError):
                    code, status, retry = "upstream_unavailable", 502, 1
                elif isinstance(error, (RedisError, asyncpg.PostgresError, OSError)):
                    code, status, retry = "limiter_unavailable", 503, 1
                else:
                    code, status, retry = "internal_error", 500, 1
                event.update(error_code=code, status=status)
                if status == 499:
                    if isinstance(error, asyncio.CancelledError):
                        raise
                elif headers_sent:
                    raise RuntimeError("Proxy stream interrupted") from None
                else:
                    response_body = {"error": code}
                    response_headers = {"Cache-Control": "no-store"}
                    if retry is not None:
                        response_headers["Retry-After"] = str(retry)
                    if isinstance(error, InvalidRequest):
                        if error.details is not None:
                            response_body["details"] = error.details
                        if error.allow:
                            response_headers["Allow"] = error.allow
                    # Escape field names too: JSON keys may contain lone surrogates.
                    await Response(
                        json.dumps(response_body),
                        media_type="application/json",
                        status_code=status,
                        headers=response_headers,
                    )(scope, receive, tracked_send)
            finally:
                for task in (watcher, work):
                    if task is not None:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await task
                if claimed:
                    state.budget.leave(body_size)
                event["request_bytes"] = body_size
                event["duration_ms"] = (time.monotonic() - started) * 1000
                state.telemetry.count(event, secrets)
                if event["error_code"]:
                    state.telemetry.error(event, secrets)

    app.router.add_route("/{path:path}", ProxyEndpoint(), methods=None)
    return app


app = create_app()
