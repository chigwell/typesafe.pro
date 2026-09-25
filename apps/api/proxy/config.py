import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_network
from urllib.parse import urlsplit

UPSTREAM = "https://api.typesafe.ai"
MAX_BODY_BYTES = 10 * 1024 * 1024
MASTER_REQUESTS_PER_MINUTE = 1_200
MASTER_TOKENS_PER_SECOND = 250_000
MAX_CONTEXT_TOKENS = 64_000
MAX_STATE_QUESTION_TOKENS = 32_000
RETENTION_SECONDS = 7 * 24 * 60 * 60
TOKEN_NAME = re.compile(r"TYPESAFE_(TEST|MASTER|ADMIN)_API_TOKEN_([1-9][0-9]*)$")
TIERS = ("paid", "free", "anonymous")


@dataclass(frozen=True)
class MasterKey:
    key_id: str
    secret: bytes = field(repr=False)


@dataclass(frozen=True)
class Policy:
    tier: str
    rpm: int
    burst: int
    queue_wait: float
    queue_size: int


DEFAULT_POLICIES = {
    "anonymous": Policy("anonymous", 30, 5, 3, 64),
    "free": Policy("free", 120, 10, 10, 128),
    "paid": Policy("paid", 1000, 20, 30, 256),
}


@dataclass(frozen=True)
class Settings:
    masters: tuple[MasterKey, ...]
    legacy_tokens: tuple[bytes, ...] = field(repr=False)
    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    hash_secret: bytes = field(repr=False)
    trusted_proxies: tuple = ()
    queue_memory_bytes: int = 64 * 1024 * 1024
    max_pending: int = 512
    max_inflight: int = 32
    master_max_inflight: int = 8
    request_timeout: int = 90
    release_sha: str = "development"
    admin_password: bytes = field(default=b"", repr=False)
    admin_session_ttl_seconds: int = 28800
    admin_login_max_attempts: int = 5
    admin_login_window_seconds: int = 900
    admin_allowed_origins: tuple[str, ...] = ("https://typesafe.pro",)
    observability_retention_seconds: int = RETENTION_SECONDS
    host_proc_path: str = "/proc"
    host_disk_path: str = "/"
    admin_tokens: tuple[bytes, ...] = field(default=(), repr=False)
    analytics_view_rpm: int = 30
    analytics_view_burst: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        keys: dict[str, dict[str, bytes]] = {}
        admins: dict[str, bytes] = {}
        for name, value in env.items():
            if not name.startswith(
                (
                    "TYPESAFE_TEST_API_TOKEN_",
                    "TYPESAFE_MASTER_API_TOKEN_",
                    "TYPESAFE_ADMIN_API_TOKEN_",
                )
            ):
                continue
            match = TOKEN_NAME.fullmatch(name)
            if match is not None and match.group(1) == "TEST" and not value:
                continue
            if match is None or not re.fullmatch(r"[\x21-\x7e]+", value):
                raise ValueError("Invalid token configuration (names or values)")
            kind, key_id = match.groups()
            if kind == "ADMIN":
                admins[key_id] = value.encode("ascii")
                continue
            keys.setdefault(key_id, {})[kind] = value.encode("ascii")
        if not keys or any("MASTER" not in pair for pair in keys.values()):
            raise ValueError("At least one master is required; legacy tokens need a matching index")
        clients = [pair["TEST"] for pair in keys.values() if "TEST" in pair]
        masters = [pair["MASTER"] for pair in keys.values()]
        admin_tokens = list(admins.values())
        if (
            len(set(clients)) != len(clients)
            or len(set(masters)) != len(masters)
            or len(set(admin_tokens)) != len(admin_tokens)
            or set(clients) & set(masters)
            or set(clients) & set(admin_tokens)
            or set(masters) & set(admin_tokens)
        ):
            raise ValueError("Tokens must be unique and client/master/admin tokens must differ")
        required = ("DATABASE_URL", "REDIS_URL", "TOKEN_HASH_SECRET")
        missing = [
            name for name in required if not env.get(name) or "\n" in env[name] or "\r" in env[name]
        ]
        if missing:
            raise ValueError("Missing required settings: " + ", ".join(missing))
        if len(env["TOKEN_HASH_SECRET"]) < 32:
            raise ValueError("TOKEN_HASH_SECRET must contain at least 32 characters")
        password = env.get("ADMIN_PASSWORD", "")
        if not re.fullmatch(r"[\x21-\x7e]{32,256}", password):
            raise ValueError("ADMIN_PASSWORD must contain 32 to 256 printable ASCII characters")
        origins = tuple(
            value.strip()
            for value in env.get("ADMIN_ALLOWED_ORIGINS", "https://typesafe.pro").split(",")
            if value.strip()
        )
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"))
            ):
                raise ValueError("ADMIN_ALLOWED_ORIGINS must contain exact HTTPS origins")
        if not origins:
            raise ValueError("ADMIN_ALLOWED_ORIGINS must not be empty")

        def positive(name, default):
            try:
                value = int(env.get(name, str(default)))
                if value > 0:
                    return value
            except ValueError:
                pass
            raise ValueError(f"{name} must be a positive integer")

        retention = positive("OBSERVABILITY_RETENTION_SECONDS", RETENTION_SECONDS)
        if retention < 300 or retention % 60:
            raise ValueError("OBSERVABILITY_RETENTION_SECONDS must be whole minutes, at least 300")

        try:
            trusted = tuple(
                ip_network(value.strip())
                for value in env.get("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128").split(",")
                if value.strip()
            )
        except ValueError:
            raise ValueError("Invalid TRUSTED_PROXY_CIDRS") from None
        return cls(
            masters=tuple(MasterKey(key, keys[key]["MASTER"]) for key in sorted(keys, key=int)),
            legacy_tokens=tuple(clients),
            database_url=env["DATABASE_URL"],
            redis_url=env["REDIS_URL"],
            hash_secret=env["TOKEN_HASH_SECRET"].encode(),
            trusted_proxies=trusted,
            queue_memory_bytes=positive("QUEUE_MEMORY_BYTES", 64 * 1024 * 1024),
            max_pending=positive("MAX_PENDING_REQUESTS", 512),
            max_inflight=positive("MAX_INFLIGHT_REQUESTS", 32),
            master_max_inflight=positive("MASTER_MAX_INFLIGHT", 8),
            request_timeout=positive("REQUEST_TIMEOUT_SECONDS", 90),
            release_sha=env.get("RELEASE_SHA", "development"),
            admin_password=password.encode("ascii"),
            admin_session_ttl_seconds=positive("ADMIN_SESSION_TTL_SECONDS", 28800),
            admin_login_max_attempts=positive("ADMIN_LOGIN_MAX_ATTEMPTS", 5),
            admin_login_window_seconds=positive("ADMIN_LOGIN_WINDOW_SECONDS", 900),
            admin_allowed_origins=origins,
            observability_retention_seconds=retention,
            host_proc_path=env.get("HOST_PROC_PATH", "/proc"),
            host_disk_path=env.get("HOST_DISK_PATH", "/"),
            admin_tokens=tuple(admins[key] for key in sorted(admins, key=int)),
            analytics_view_rpm=positive("ANALYTICS_VIEW_RPM", 30),
            analytics_view_burst=positive("ANALYTICS_VIEW_BURST", 10),
        )
