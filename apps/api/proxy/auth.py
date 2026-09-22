import hashlib
import hmac
import re
from dataclasses import dataclass
from ipaddress import ip_address
from secrets import compare_digest

from .config import Settings


def digest(secret: bytes, value: bytes, domain: str = "token") -> str:
    return hmac.new(secret, domain.encode() + b":" + value, hashlib.sha256).hexdigest()


def bearer(headers: list[tuple[bytes, bytes]]) -> bytes | None:
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if len(values) != 1 or len(values[0]) > 4096:
        return None
    match = re.fullmatch(rb"(?i:Bearer) +([\x21-\x7e]+)", values[0])
    return match.group(1) if match else None


def client_ip(scope, trusted_proxies) -> str:
    try:
        peer = ip_address((scope.get("client") or ("0.0.0.0", 0))[0])
    except ValueError:
        return "0.0.0.0"
    if any(peer in network for network in trusted_proxies):
        # nginx overwrites these headers with one normalized address. Never accept a chain.
        for header in (b"x-real-ip", b"x-forwarded-for"):
            values = [value for name, value in scope["headers"] if name.lower() == header]
            if len(values) == 1:
                try:
                    return str(ip_address(values[0].decode("ascii")))
                except (ValueError, UnicodeError):
                    pass
    return str(peer)


@dataclass(frozen=True)
class Identity:
    tier: str
    client_hash: str
    ip_hash: str


async def authenticate(scope, settings: Settings, store, redis) -> Identity:
    ip_hash = digest(
        settings.hash_secret, client_ip(scope, settings.trusted_proxies).encode(), "ip"
    )
    candidate = bearer(scope["headers"])
    if candidate:
        hashed = digest(settings.hash_secret, candidate)
        if any(compare_digest(candidate, token) for token in settings.admin_tokens):
            return Identity("admin", hashed, ip_hash)
        if any(compare_digest(candidate, token) for token in settings.legacy_tokens):
            return Identity("free", hashed, ip_hash)
        # Unknown tokens are not cached: rotating random credentials must not fill Redis.
        tier = await redis.get("ts:auth:" + hashed)
        if tier is None:
            record = await store.lookup_token(hashed)
            if record:
                tier, ttl = record
                if ttl <= 0:
                    tier = None
                else:
                    await redis.set("ts:auth:" + hashed, tier, ex=min(30, ttl))
        if tier in ("free", "paid"):
            return Identity(tier, hashed, ip_hash)
    return Identity("anonymous", ip_hash, ip_hash)
