"""Append-only page storage with hashes, compact indexes and resumable releases."""

import hashlib
import json
import os
import re
from pathlib import Path

from .models import Idea, Manifest, Page, Release, ReleasePage, Shard, ShardEntry

MAX_BYTES = 1_048_576
MAX_PAGES = 100


class CatalogError(ValueError):
    """Corrupt data must stop a deployment, unlike provider unavailability."""


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def encoded(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def compact(page: Page | Idea) -> dict:
    keys = Idea.model_fields.keys()
    return {key: getattr(page, key) for key in keys}


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def fingerprint(page: Page | Idea) -> str:
    return sha256(
        canonical(
            [
                normalized(getattr(page, key))
                for key in ("problem", "input_description", "decision", "action")
            ]
        )
    )


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.pages: list[Page] = []
        self.manifest: Manifest
        self.recover_append()
        self.load()

    def load(self) -> None:
        try:
            self.manifest = Manifest.model_validate_json((self.path / "manifest.json").read_bytes())
            entries = [entry.model_dump() for entry in self.manifest.shards]
            if sha256(canonical(entries)) != self.manifest.catalog_hash:
                raise CatalogError("catalog checksum mismatch")
            self.pages = []
            seen_files = set()
            for entry in self.manifest.shards:
                if entry.file in seen_files:
                    raise CatalogError("duplicate shard entry")
                seen_files.add(entry.file)
                raw = (self.path / entry.file).read_bytes()
                if len(raw) > MAX_BYTES or sha256(raw) != entry.sha256:
                    raise CatalogError("shard checksum or size mismatch")
                shard = Shard.model_validate_json(raw)
                if len(shard.pages) != entry.count:
                    raise CatalogError("shard count mismatch")
                index_file = self.path / entry.file.replace("pages-", "index-")
                expected_index = {
                    "schema_version": 1,
                    "scenarios": [compact(p) for p in shard.pages],
                }
                if json.loads(index_file.read_bytes()) != expected_index:
                    raise CatalogError("compact index differs from page data")
                self.pages.extend(shard.pages)
            if len(self.pages) != self.manifest.total:
                raise CatalogError("catalog count mismatch")
            if len({page.slug for page in self.pages}) != len(self.pages):
                raise CatalogError("duplicate slug")
            if len({fingerprint(page) for page in self.pages}) != len(self.pages):
                raise CatalogError("duplicate scenario fingerprint")
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, CatalogError):
                raise
            raise CatalogError("invalid catalog schema or missing file") from None

    def recover_append(self) -> None:
        """Replay only a fully validated one-page write-ahead transaction.

        The journal is fsynced before touching any existing catalog file. Recovery is
        idempotent even if interrupted after the shard, index or manifest replacement.
        """
        journal_path = self.path / "append-journal.json"
        if not journal_path.exists():
            return
        try:
            if journal_path.stat().st_size > 4 * MAX_BYTES:
                raise CatalogError("append journal exceeds its size limit")
            journal = json.loads(journal_path.read_bytes())
            if (
                set(journal)
                != {
                    "schema_version",
                    "file",
                    "before_manifest",
                    "after_manifest",
                    "before_shard",
                    "after_shard",
                }
                or journal["schema_version"] != 1
            ):
                raise CatalogError("invalid append journal shape")
            before = Manifest.model_validate(journal["before_manifest"])
            after = Manifest.model_validate(journal["after_manifest"])
            for manifest in (before, after):
                entries = [entry.model_dump() for entry in manifest.shards]
                if (
                    manifest.catalog_hash != sha256(canonical(entries))
                    or manifest.total != sum(entry.count for entry in manifest.shards)
                    or len({entry.file for entry in manifest.shards}) != len(entries)
                ):
                    raise CatalogError("invalid journal manifest")
            current = Manifest.model_validate_json((self.path / "manifest.json").read_bytes())
            if current not in (before, after):
                raise CatalogError("append journal does not belong to the current catalog")
            target = Shard.model_validate(journal["after_shard"])
            name = journal["file"]
            raw_target = encoded(journal["after_shard"])
            if not after.shards or name != after.shards[-1].file or len(raw_target) > MAX_BYTES:
                raise CatalogError("invalid journal target")
            expected_entry = ShardEntry(
                file=name, count=len(target.pages), sha256=sha256(raw_target)
            )
            if after.shards[-1] != expected_entry or after.total != before.total + 1:
                raise CatalogError("journal must append exactly one page")
            if journal["before_shard"] is None:
                if (
                    name != f"pages-{len(before.shards) + 1:04d}.json"
                    or after.shards[:-1] != before.shards
                    or len(target.pages) != 1
                ):
                    raise CatalogError("journal may only create the next numbered shard")
                old_index = None
                old_bytes = None
            else:
                old = Shard.model_validate(journal["before_shard"])
                old_bytes = encoded(journal["before_shard"])
                if (
                    not before.shards
                    or name != before.shards[-1].file
                    or sha256(old_bytes) != before.shards[-1].sha256
                    or len(old.pages) != before.shards[-1].count
                    or target.pages[:-1] != old.pages
                    or after.shards[:-1] != before.shards[:-1]
                ):
                    raise CatalogError("journal changes existing pages")
                old_index = {"schema_version": 1, "scenarios": [compact(p) for p in old.pages]}
            # Validate every unaffected record before replay can touch existing bytes.
            unaffected = before.shards if old_bytes is None else before.shards[:-1]
            all_pages = list(target.pages)
            for entry in unaffected:
                raw = (self.path / entry.file).read_bytes()
                shard = Shard.model_validate_json(raw)
                expected_index = {
                    "schema_version": 1,
                    "scenarios": [compact(p) for p in shard.pages],
                }
                if (
                    sha256(raw) != entry.sha256
                    or len(raw) > MAX_BYTES
                    or len(shard.pages) != entry.count
                    or json.loads((self.path / entry.file.replace("pages-", "index-")).read_bytes())
                    != expected_index
                ):
                    raise CatalogError("unaffected catalog data is corrupt")
                all_pages.extend(shard.pages)
            if len({page.slug for page in all_pages}) != len(all_pages) or len(
                {fingerprint(page) for page in all_pages}
            ) != len(all_pages):
                raise CatalogError("append journal contains duplicate records")
            target_index = {"schema_version": 1, "scenarios": [compact(p) for p in target.pages]}
            shard_path = self.path / name
            index_path = self.path / name.replace("pages-", "index-")
            observed = shard_path.read_bytes() if shard_path.exists() else None
            if observed not in (old_bytes, raw_target):
                raise CatalogError("journal target contains unrelated changes")
            observed_index = json.loads(index_path.read_bytes()) if index_path.exists() else None
            if observed_index not in (old_index, target_index):
                raise CatalogError("journal index contains unrelated changes")
            atomic_write(shard_path, journal["after_shard"])
            atomic_write(index_path, target_index)
            atomic_write(self.path / "manifest.json", after.model_dump())
            self.load()
            journal_path.unlink()
            sync_directory(self.path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, CatalogError):
                raise
            raise CatalogError("invalid or incomplete append journal") from None

    def add(self, page: Page) -> None:
        if any(p.slug == page.slug or fingerprint(p) == fingerprint(page) for p in self.pages):
            raise CatalogError("cannot append duplicate page")
        entries = [entry.model_copy(deep=True) for entry in self.manifest.shards]
        shard_pages = []
        if entries:
            last = entries[-1]
            shard_pages = Shard.model_validate_json((self.path / last.file).read_bytes()).pages
        candidate = {
            "schema_version": 1,
            "pages": [p.model_dump(exclude_none=True) for p in [*shard_pages, page]],
        }
        if len(shard_pages) >= MAX_PAGES or len(encoded(candidate)) > MAX_BYTES:
            shard_pages = []
        if not shard_pages:
            name = f"pages-{len(entries) + 1:04d}.json"
            candidate = {"schema_version": 1, "pages": [page.model_dump(exclude_none=True)]}
        else:
            name = entries.pop().file
        raw = encoded(candidate)
        if len(raw) > MAX_BYTES:
            raise CatalogError("single page exceeds shard size limit")
        entry = ShardEntry(file=name, count=len(candidate["pages"]), sha256=sha256(raw))
        entries.append(entry)
        manifest = Manifest(
            total=self.manifest.total + 1,
            shards=entries,
            catalog_hash=sha256(canonical([item.model_dump() for item in entries])),
        )
        before_shard = None
        if shard_pages:
            before_shard = json.loads((self.path / name).read_bytes())
        atomic_write(
            self.path / "append-journal.json",
            {
                "schema_version": 1,
                "file": name,
                "before_manifest": self.manifest.model_dump(),
                "after_manifest": manifest.model_dump(),
                "before_shard": before_shard,
                "after_shard": candidate,
            },
        )
        self.recover_append()

    def validate_release(self) -> Release:
        try:
            release = Release.model_validate_json((self.path / "release.json").read_bytes())
            if release.catalog_hash != self.manifest.catalog_hash:
                raise CatalogError("release checksum differs from catalog")
            by_slug = {page.slug: page for page in self.pages}
            if len({p.slug for p in release.pages}) != len(release.pages):
                raise CatalogError("duplicate release slug")
            for item in release.pages:
                page = by_slug.get(item.slug)
                if page is None or item != release_page(page):
                    raise CatalogError("release page missing or metadata differs")
            return release
        except (OSError, ValueError) as exc:
            if isinstance(exc, CatalogError):
                raise
            raise CatalogError("invalid release") from None


def release_page(page: Page) -> ReleasePage:
    return ReleasePage(
        slug=page.slug, title=page.seo.title, created_at=page.created_at, updated_at=page.updated_at
    )


def baseline_slugs(path: Path, catalog: Catalog) -> list[str]:
    try:
        data = json.loads(path.read_bytes())
        # The database has no publication time/hash before the first successful release.
        if data == {
            "schema_version": 1,
            "run_id": "",
            "source_sha": "",
            "catalog_hash": "",
            "generated_at": None,
            "pages": [],
        }:
            return []
        baseline = Release.model_validate(data)
        slugs = [page.slug for page in baseline.pages]
        by_slug = {page.slug: page for page in catalog.pages}
        if len(set(slugs)) != len(slugs):
            raise CatalogError("duplicate baseline slug")
        for page in baseline.pages:
            if page.slug not in by_slug or page != release_page(by_slug[page.slug]):
                raise CatalogError("published baseline differs from immutable catalog")
        return slugs
    except (OSError, ValueError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError("invalid publication baseline") from None
