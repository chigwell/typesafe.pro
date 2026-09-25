"""Copy explicitly selected local content credentials to GitHub Actions via stdin."""

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

NAMES = ("LLM7_BASE_URL", "LLM7_MODEL", "LLM7_TOKEN", "TYPESAFE_ADMIN_API_TOKEN_1")


def settings(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=(.*)$", line)
        if not match or match[1] not in NAMES:
            continue
        name, value = match[1], match[2].strip()
        if name in values:
            raise ValueError(f"Duplicate {name}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Invalid quoted {name}")
            value = value[1:-1]
        if not value or not re.fullmatch(r"[\x21-\x7e]{1,4096}", value):
            raise ValueError(f"Invalid {name}")
        values[name] = value
    if missing := set(NAMES) - set(values):
        raise ValueError("Missing variables: " + ", ".join(sorted(missing)))
    url = urlsplit(values["LLM7_BASE_URL"])
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "LLM7_BASE_URL must be an HTTPS API base without credentials or query"
        )
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Validate locally without uploading"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["git", "check-ignore", "--quiet", ".env"], cwd=root, check=True)
    values = settings(root / ".env")
    for name in NAMES:
        if not args.check:
            subprocess.run(
                ["gh", "secret", "set", name, "--repo", "chigwell/typesafe.pro"],
                input=values[name],
                text=True,
                check=True,
                capture_output=True,
            )
        print(
            f"{name}: {'validated' if args.check else 'configured in GitHub Actions'}"
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise SystemExit("Content secret configuration failed: " + detail) from None
