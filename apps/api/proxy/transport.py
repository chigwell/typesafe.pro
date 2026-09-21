from collections.abc import Callable

import anyio
import httpx
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from .config import UPSTREAM

HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"proxy-connection",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}


def end_to_end(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    excluded = HOP_HEADERS.copy()
    for name, value in headers:
        if name.lower() == b"connection":
            excluded.update(part.strip().lower() for part in value.split(b","))
    return [(name.lower(), value) for name, value in headers if name.lower() not in excluded]


def upstream_request(scope: Scope, body: bytes, master: bytes) -> httpx.Request:
    path = scope["raw_path"]
    if scope["query_string"]:
        path += b"?" + scope["query_string"]
    # copy_with keeps the authority fixed, including for a path beginning with //.
    url = httpx.URL(UPSTREAM).copy_with(raw_path=path)
    headers = [
        (name, value)
        for name, value in end_to_end(scope["headers"])
        if name
        not in {
            b"host",
            b"authorization",
            b"content-length",
            b"x-request-id",
            b"x-real-ip",
            b"x-forwarded-for",
            b"cf-connecting-ip",
        }
    ]
    headers.append((b"authorization", b"Bearer " + master))
    if "request_id" in scope:
        headers.append((b"x-request-id", scope["request_id"].encode()))
    # Do not use client.build_request: its cookie jar would cross client boundaries.
    return httpx.Request(scope["method"], url, headers=headers, content=body)


class ProxyResponse(StreamingResponse):
    def __init__(self, upstream: httpx.Response, observe: Callable | None = None):
        self.upstream = upstream

        async def stream():
            async for chunk in upstream.aiter_raw():
                if observe:
                    observe(chunk)
                yield chunk

        super().__init__(stream(), status_code=upstream.status_code)
        self.raw_headers = end_to_end(upstream.headers.raw)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.upstream.aclose()
