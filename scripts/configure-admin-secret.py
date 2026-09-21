"""Generate/reuse a private local password and upload it to GitHub without printing it."""

import argparse
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    subprocess.run(["git", "check-ignore", "--quiet", ".env"], cwd=root, check=True)
    if target.is_symlink():
        raise ValueError("Refusing to replace a symlinked .env")
    existing = target.read_text() if target.exists() else ""
    entries = re.findall(r"^ADMIN_PASSWORD=(.*)$", existing, re.MULTILINE)
    if len(entries) > 1:
        raise ValueError("Multiple ADMIN_PASSWORD entries in .env")
    password = entries[0] if entries and entries[0] else secrets.token_urlsafe(48)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", password):
        raise ValueError("Existing ADMIN_PASSWORD is not a valid generated password")
    entry = "ADMIN_PASSWORD=" + password
    content = (
        re.sub(r"^ADMIN_PASSWORD=.*$", entry, existing, flags=re.MULTILINE)
        if entries
        else existing.rstrip("\n") + "\n" + entry + "\n"
    )
    # Atomic replacement preserves unrelated settings and keeps the secret owner-readable only.
    fd, temporary = tempfile.mkstemp(dir=root, prefix=".env.admin-")
    try:
        with os.fdopen(fd, "w") as output:
            output.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("ADMIN_PASSWORD is stored in ignored .env (mode 0600).")
    if not args.local_only:
        subprocess.run(
            [
                "gh",
                "secret",
                "set",
                "ADMIN_PASSWORD",
                "--repo",
                "chigwell/typesafe.pro",
            ],
            input=password,
            text=True,
            check=True,
        )
        print("GitHub Actions secret ADMIN_PASSWORD updated for chigwell/typesafe.pro.")


if __name__ == "__main__":
    main()
