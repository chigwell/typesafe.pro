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
    values["RATE_LIMIT_PER_MINUTE"] = os.environ.get("RATE_LIMIT_PER_MINUTE", "60")
    values["RATE_LIMIT_BURST"] = os.environ.get("RATE_LIMIT_BURST", "10")
    with os.fdopen(
        os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as output:
        output.write("".join(f"{name}={value}\n" for name, value in values.items()))


if __name__ == "__main__":
    main()
