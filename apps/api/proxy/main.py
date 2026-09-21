import time
from collections.abc import Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from .auth import authenticate
from .config import MAX_BODY_BYTES, Settings
from .limiter import TokenBucket
from .transport import ProxyResponse, upstream_request


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or Settings.from_env()
        app.state.limiter = TokenBucket(
            app.state.settings.rate_per_minute, app.state.settings.burst, clock
        )
        async with httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=httpx.Timeout(connect=5, read=60, write=60, pool=5),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.router.redirect_slashes = False

    @app.get("/health")
    async def health(request: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "service": "typesafe-proxy",
                "release": request.app.state.settings.release_sha,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def proxy(request: Request) -> Response:
        state = request.app.state
        pair = authenticate(request.scope["headers"], state.settings.tokens)
        if pair is None:
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
        retry = state.limiter.retry_after(pair.key_id)
        if retry:
            return JSONResponse(
                {"error": "rate_limit_exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry), "Cache-Control": "no-store"},
            )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return JSONResponse({"error": "request_too_large"}, status_code=413)
            body.extend(chunk)
        try:
            upstream = await state.client.send(
                upstream_request(request.scope, bytes(body), pair.master), stream=True
            )
        except httpx.TimeoutException:
            return JSONResponse({"error": "upstream_timeout"}, status_code=504)
        except httpx.HTTPError:
            return JSONResponse({"error": "upstream_unavailable"}, status_code=502)
        return ProxyResponse(upstream)

    class ProxyEndpoint:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            response = await proxy(Request(scope, receive))
            await response(scope, receive, send)

    # An ASGI endpoint leaves the HTTP method unrestricted and avoids body schema parsing.
    app.router.add_route("/{path:path}", ProxyEndpoint(), methods=None)
    return app


app = create_app()
