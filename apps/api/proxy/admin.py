import asyncio
import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from .auth import client_ip, digest
from .telemetry import sanitize

COOKIE = "__Secure-typesafe_admin"
COOKIE_PATH = "/admin/api"
WINDOW = Literal["5m", "1h", "24h", "7d"]
ATTEMPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count >= tonumber(ARGV[1]) then
    return math.max(1, redis.call('TTL', KEYS[1]))
end
count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
return 0
"""


def session_cookie(settings, now=None):
    expires = int(time.time() if now is None else now) + settings.admin_session_ttl_seconds
    payload = f"v1.{expires}.{secrets.token_urlsafe(24)}"
    signature = digest(settings.admin_password, payload.encode(), "admin-session")
    return payload + "." + signature


def valid_session(value, settings, now=None):
    if not value or len(value) > 256 or not settings.admin_password:
        return False
    try:
        version, expiry, nonce, signature = value.split(".")
        current = int(time.time() if now is None else now)
        if (
            version != "v1"
            or not nonce
            or not current < int(expiry) <= current + settings.admin_session_ttl_seconds
        ):
            return False
        payload = f"{version}.{expiry}.{nonce}"
        expected = digest(settings.admin_password, payload.encode(), "admin-session")
        return hmac.compare_digest(signature.encode(), expected.encode())
    except (ValueError, UnicodeError):
        return False


def require_admin(request: Request):
    if not valid_session(request.cookies.get(COOKIE), request.app.state.settings):
        raise HTTPException(401, "Admin session required")


def admin_router():
    router = APIRouter(prefix=COOKIE_PATH)
    protected = APIRouter(dependencies=[Depends(require_admin)])

    @router.post("/auth/login")
    async def login(request: Request):
        state = request.app.state
        config = state.settings
        ip = client_ip(request.scope, config.trusted_proxies)
        key = "ts:admin:login:" + digest(config.hash_secret, ip.encode(), "admin-login")
        try:
            retry = await state.redis.eval(
                ATTEMPT, 1, key, config.admin_login_max_attempts, config.admin_login_window_seconds
            )
        except Exception:
            raise HTTPException(
                503, "Login temporarily unavailable", headers={"Retry-After": "5"}
            ) from None
        if retry:
            raise HTTPException(429, "Too many login attempts", headers={"Retry-After": str(retry)})
        try:
            body = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 4096:
                        raise HTTPException(413, "Login request too large")
                    body.extend(chunk)
            data = json.loads(body)
            password = data.get("password") if isinstance(data, dict) else None
            if not isinstance(password, str):
                raise ValueError
            candidate = password.encode("utf-8")
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            raise HTTPException(400, "Invalid login request") from None
        if not hmac.compare_digest(
            hashlib.sha256(candidate).digest(),
            hashlib.sha256(config.admin_password).digest(),
        ):
            raise HTTPException(401, "Invalid password")
        try:
            await state.redis.delete(key)
        except Exception:
            raise HTTPException(503, "Login temporarily unavailable") from None
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            COOKIE,
            session_cookie(config),
            max_age=config.admin_session_ttl_seconds,
            path=COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response

    @router.post("/auth/logout")
    async def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(
            COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict"
        )
        return response

    @protected.get("/auth/session")
    async def session():
        return {"authenticated": True}

    @protected.get("/system")
    async def system(request: Request):
        return await request.app.state.system.status(request.app.state)

    @protected.get("/summary")
    async def summary(request: Request, window: WINDOW = "24h"):
        try:
            result = await request.app.state.telemetry.activity.snapshot(window)
            return {key: value for key, value in result.items() if key != "ip_key"}
        except Exception:
            raise HTTPException(503, "Activity data temporarily unavailable") from None

    @protected.get("/ip-activity")
    async def ip_activity(
        request: Request,
        window: WINDOW = "24h",
        page: Annotated[int, Query(ge=1, le=100000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ):
        try:
            return await request.app.state.telemetry.activity.ip_page(window, page, page_size)
        except Exception:
            raise HTTPException(503, "IP activity temporarily unavailable") from None

    @protected.get("/errors")
    async def errors(
        request: Request,
        page: Annotated[int, Query(ge=1, le=100000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        status: Annotated[int | None, Query(ge=100, le=599)] = None,
        error_code: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+$")] = None,
    ):
        state = request.app.state
        try:
            result = await state.store.error_page(page, page_size, status, error_code)
        except Exception:
            raise HTTPException(503, "Error history temporarily unavailable") from None
        config = state.settings
        credentials = [
            config.admin_password,
            config.hash_secret,
            config.database_url,
            config.redis_url,
            *config.admin_tokens,
            *config.legacy_tokens,
            *(key.secret for key in config.masters),
        ]
        for row in result["items"]:
            row["id"] = str(row["id"])
            row["client_ip"] = str(row["client_ip"]) if row["client_ip"] is not None else None
            for key, value in row.items():
                if isinstance(value, str):
                    row[key] = sanitize(value, credentials)
        return JSONResponse(jsonable_encoder(result))

    router.include_router(protected)
    return router
