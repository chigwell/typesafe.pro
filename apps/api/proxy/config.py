import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

UPSTREAM = "https://api.typesafe.ai"
MAX_BODY_BYTES = 10 * 1024 * 1024
TOKEN_NAME = re.compile(r"TYPESAFE_(TEST|MASTER)_API_TOKEN_([1-9][0-9]*)$")


@dataclass(frozen=True)
class TokenPair:
    key_id: str
    client: bytes = field(repr=False)
    master: bytes = field(repr=False)


@dataclass(frozen=True)
class Settings:
    tokens: tuple[TokenPair, ...]
    rate_per_minute: int = 60
    burst: int = 10
    release_sha: str = "development"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        pairs: dict[str, dict[str, bytes]] = {}
        for name, value in env.items():
            if not name.startswith(("TYPESAFE_TEST_API_TOKEN_", "TYPESAFE_MASTER_API_TOKEN_")):
                continue
            match = TOKEN_NAME.fullmatch(name)
            if match is None or not re.fullmatch(r"[\x21-\x7e]+", value):
                raise ValueError("Invalid token configuration (names or values)")
            kind, key_id = match.groups()
            pairs.setdefault(key_id, {})[kind] = value.encode("ascii")
        if not pairs or any(set(pair) != {"TEST", "MASTER"} for pair in pairs.values()):
            raise ValueError("At least one complete TEST/MASTER token pair is required")
        clients = [pair["TEST"] for pair in pairs.values()]
        masters = {pair["MASTER"] for pair in pairs.values()}
        if len(set(clients)) != len(clients) or set(clients) & masters:
            raise ValueError("Client tokens must be unique and distinct from master tokens")
        try:
            rate = int(env.get("RATE_LIMIT_PER_MINUTE", "60"))
            burst = int(env.get("RATE_LIMIT_BURST", "10"))
        except ValueError:
            raise ValueError("Rate limits must be positive integers") from None
        if rate <= 0 or burst <= 0:
            raise ValueError("Rate limits must be positive integers")
        return cls(
            tokens=tuple(
                TokenPair(key, pair["TEST"], pair["MASTER"]) for key, pair in pairs.items()
            ),
            rate_per_minute=rate,
            burst=burst,
            release_sha=env.get("RELEASE_SHA", "development"),
        )
