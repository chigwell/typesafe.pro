"""Coordinate static content publication without exposing credentials or API mutations."""

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://typesafe.pro"
CONTENT = "content/use-cases/"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ReleaseError(Exception):
    pass


def command(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def git(*args):
    return command(["git", *args], capture_output=True, text=True).stdout.strip()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def validate_manifest(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ReleaseError("Invalid publication manifest version")
    pages = value.get("pages")
    if not isinstance(pages, list):
        raise ReleaseError("Invalid publication inventory")
    seen = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ReleaseError("Invalid publication page")
        slug = page.get("slug")
        if not isinstance(slug, str) or len(slug) > 160 or not SLUG.fullmatch(slug):
            raise ReleaseError("Invalid publication slug")
        if slug in seen:
            raise ReleaseError("Duplicate publication slug")
        seen.add(slug)
        if not all(
            isinstance(page.get(key), str)
            for key in ("title", "created_at", "updated_at")
        ):
            raise ReleaseError("Incomplete publication page")
    if pages and not all(
        value.get(key)
        for key in ("run_id", "source_sha", "catalog_hash", "generated_at")
    ):
        raise ReleaseError("Incomplete publication identity")
    return value


def remote(operation, payload=None):
    """The only remote commands are fixed private CLI operations over existing SSH."""
    if operation not in {"snapshot", "record-run", "publish"}:
        raise ReleaseError("Unsupported private operation")
    host = os.environ.get("SSH_HOST", "")
    user = os.environ.get("SSH_USER", "")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host) or not re.fullmatch(
        r"[a-z_][a-z0-9_-]*", user
    ):
        raise ReleaseError("Missing or invalid SSH destination")
    with tempfile.TemporaryDirectory(prefix="typesafe-seo-ssh-") as temporary:
        directory = Path(temporary)
        key, hosts = directory / "key", directory / "known_hosts"
        for target, name in ((key, "SSH_PRIVATE_KEY"), (hosts, "SSH_KNOWN_HOSTS")):
            value = os.environ.get(name)
            if not value:
                raise ReleaseError(f"Missing {name}")
            target.touch(mode=0o600)
            target.write_text(value.rstrip("\n") + "\n")
        options = [
            "ssh",
            "-i",
            str(key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={hosts}",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=4",
            f"{user}@{host}",
        ]
        invocation = (
            "docker exec -i typesafe-proxy-api /app/.venv/bin/python -m proxy.seo "
            + operation
        )
        if payload is not None:
            invocation += " --file /dev/stdin"
        result = command(
            [*options, invocation],
            input=json.dumps(payload) if payload is not None else "",
            text=True,
            capture_output=True,
            timeout=90,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None


def fetch(path, *, allow_missing=False):
    if not path.startswith("/") or path.startswith("//"):
        raise ReleaseError("Invalid production verification path")
    request = urllib.request.Request(
        SITE + path,
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "typesafe-content-release/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not response.url.startswith(SITE + "/"):
                raise ReleaseError("Verification left the production origin")
            body = response.read(MAX_MANIFEST_BYTES + 1)
            if len(body) > MAX_MANIFEST_BYTES:
                raise ReleaseError("Production response exceeds verification limit")
            return body
    except urllib.error.HTTPError as error:
        if error.code == 404 and allow_missing:
            return None
        raise ReleaseError(
            f"Production verification returned HTTP {error.code}"
        ) from None


def production_manifest(*, allow_missing=False):
    # Cache-busting matters when reconciling after a completed Pages deployment.
    raw = fetch(
        f"/use-cases-manifest.json?verification={time.time_ns()}",
        allow_missing=allow_missing,
    )
    return validate_manifest(json.loads(raw)) if raw is not None else None


def baseline(output):
    previous = validate_manifest(remote("snapshot"))
    live = production_manifest(allow_missing=True)
    if live is None:
        if previous["pages"]:
            raise ReleaseError(
                "Production manifest is missing for an existing publication"
            )
    elif live.get("run_id") and live != previous:
        # Recover a publication whose final journal write was interrupted.
        verify_inventory(live, previous)
        remote("publish", live)
        previous = validate_manifest(remote("snapshot"))
        if previous != live:
            raise ReleaseError("Production and publication journal disagree")
    elif (
        live is not None
        and not live.get("run_id")
        and (live["pages"] or previous["pages"])
    ):
        raise ReleaseError("Production manifest has no publication identity")
    write_json(output, previous)


def ci_only():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ReleaseError("Git publication commands are restricted to GitHub Actions")


def checkout_current():
    ci_only()
    source = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[a-f0-9]{40}", source):
        raise ReleaseError("Invalid source SHA")
    command(["git", "fetch", "origin", "main"])
    current = git("rev-parse", "origin/main")
    command(["git", "merge-base", "--is-ancestor", source, current])
    changes = git("diff", "--name-only", source, current).splitlines()
    if any(not path.startswith(CONTENT) for path in changes):
        raise ReleaseError("A newer source release supersedes this deployment")
    # A retry can reuse its previous bot content commit without rerunning inference.
    command(["git", "checkout", "--detach", current])


def assert_current(expected=None):
    expected = expected or git("rev-parse", "HEAD")
    remote_head = git("ls-remote", "origin", "refs/heads/main").split()[0]
    if remote_head != expected:
        raise ReleaseError("Main changed; refusing to publish an outdated build")


def persist():
    ci_only()
    assert_current()
    command(["git", "add", "--", CONTENT])
    staged = git("diff", "--cached", "--name-only").splitlines()
    if any(not path.startswith(CONTENT) for path in staged):
        raise ReleaseError(
            "Refusing to commit files outside the generated content catalog"
        )
    if staged:
        command(
            [
                "git",
                "-c",
                "user.name=github-actions[bot]",
                "-c",
                "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit",
                "-m",
                "chore(content): prepare verified TypeSafe use cases",
            ]
        )
        command(["git", "push", "origin", "HEAD:main"])
    sha = git("rev-parse", "HEAD")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as stream:
            stream.write(f"content_sha={sha}\n")
    return sha


def sitemap_urls(path="/sitemap.xml", seen=None):
    seen = set() if seen is None else seen
    if path in seen or len(seen) >= 1000:
        raise ReleaseError("Invalid sitemap graph")
    seen.add(path)
    root = ET.fromstring(fetch(path))
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    if root.tag == namespace + "urlset":
        return {node.text for node in root.findall(f"{namespace}url/{namespace}loc")}
    if root.tag != namespace + "sitemapindex":
        raise ReleaseError("Invalid production sitemap")
    urls = set()
    for node in root.findall(f"{namespace}sitemap/{namespace}loc"):
        if not node.text or not node.text.startswith(SITE + "/"):
            raise ReleaseError("Sitemap points outside production")
        urls.update(sitemap_urls(node.text.removeprefix(SITE), seen))
    return urls


def verify_once(expected, previous):
    live = production_manifest()
    if live != expected:
        raise ReleaseError("Production has not activated the expected content manifest")
    urls = {url.rstrip("/") for url in sitemap_urls() if url}
    for page in expected["pages"]:
        if f"{SITE}/use-cases/{page['slug']}" not in urls:
            raise ReleaseError(
                "A published use case is missing from the production sitemap"
            )
    old = {page["slug"] for page in previous["pages"]}
    for page in expected["pages"]:
        if page["slug"] in old:
            continue
        body = fetch("/use-cases/" + page["slug"]).decode("utf-8")
        if "TechArticle" not in body or f"/use-cases/{page['slug']}" not in body:
            raise ReleaseError("A new use case did not return its rendered article")


def verify(manifest, previous, attempts=6):
    expected, old = (
        validate_manifest(read_json(manifest)),
        validate_manifest(read_json(previous)),
    )
    verify_inventory(expected, old, attempts)
    remote("publish", expected)


def verify_inventory(expected, old, attempts=6):
    if (
        len({p["slug"] for p in expected["pages"]} - {p["slug"] for p in old["pages"]})
        > 5
    ):
        raise ReleaseError("Publication exceeds five new pages")
    for attempt in range(attempts):
        try:
            verify_once(expected, old)
            break
        except (ReleaseError, urllib.error.URLError, ValueError, ET.ParseError):
            if attempt + 1 == attempts:
                raise ReleaseError("Production content verification failed") from None
            time.sleep(10)


def record(report, failed=False):
    if not Path(report).exists():
        return
    value = read_json(report)
    if failed:
        value["status"] = "failed"
        value["reason"] = "deployment_failed"
        value["finished_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    remote("record-run", value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("checkout-current")
    commands.add_parser("assert-current")
    commands.add_parser("persist")
    base = commands.add_parser("baseline")
    base.add_argument("--output", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--manifest", required=True)
    check.add_argument("--baseline", required=True)
    report = commands.add_parser("record")
    report.add_argument("--report", required=True)
    report.add_argument("--failed", action="store_true")
    args = parser.parse_args()
    if args.operation == "checkout-current":
        checkout_current()
    elif args.operation == "assert-current":
        assert_current()
    elif args.operation == "persist":
        persist()
    elif args.operation == "baseline":
        baseline(args.output)
    elif args.operation == "verify":
        verify(args.manifest, args.baseline)
    else:
        record(args.report, args.failed)


if __name__ == "__main__":
    try:
        main()
    except (
        ReleaseError,
        subprocess.SubprocessError,
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        # Never print subprocess payloads, environment, or raw provider responses.
        message = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
        raise SystemExit(f"Content release failed: {message}") from None
