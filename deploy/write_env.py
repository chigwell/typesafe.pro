"""Create the raw Compose env file without printing credentials."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from proxy.config import Settings


def main():
    Settings.from_env()
    names = sorted(
        name
        for name in os.environ
        if name.startswith(("TYPESAFE_TEST_API_TOKEN_", "TYPESAFE_MASTER_API_TOKEN_"))
    )
    values = {name: os.environ[name] for name in names}
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "POSTGRES_PASSWORD",
        "TOKEN_HASH_SECRET",
        "QUEUE_MEMORY_BYTES",
        "MAX_PENDING_REQUESTS",
        "MAX_INFLIGHT_REQUESTS",
        "MASTER_MAX_INFLIGHT",
        "REQUEST_TIMEOUT_SECONDS",
    ):
        if name in os.environ:
            values[name] = os.environ[name]
    if not values.get("POSTGRES_PASSWORD"):
        raise ValueError("POSTGRES_PASSWORD is required")
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Runtime values must be single-line")
    password = values.pop("POSTGRES_PASSWORD")
    with os.fdopen(
        os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as output:
        output.write("".join(f"{name}={value}\n" for name, value in values.items()))
    with os.fdopen(
        os.open(
            Path(sys.argv[1]).with_name("postgres.env"),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        ),
        "w",
    ) as output:
        output.write(f"POSTGRES_PASSWORD={password}\n")


if __name__ == "__main__":
    main()
