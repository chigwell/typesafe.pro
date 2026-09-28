import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "content_release", Path(__file__).resolve().parents[1] / "content_release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def manifest(slugs=(), run_id="123"):
    return {
        "schema_version": 1,
        "run_id": run_id,
        "source_sha": "a" * 40,
        "catalog_hash": "b" * 64,
        "generated_at": "2026-09-25T12:00:00Z",
        "pages": [
            {
                "slug": slug,
                "title": "A useful case",
                "created_at": "2026-09-25T12:00:00Z",
                "updated_at": "2026-09-25T12:00:00Z",
            }
            for slug in slugs
        ],
    }


@pytest.mark.parametrize(
    "slug", ["../admin", "https://evil.test", "a/b", "a?b", "a#b", "A B"]
)
def test_manifest_rejects_noncanonical_slugs(slug):
    with pytest.raises(release.ReleaseError):
        release.validate_manifest(manifest([slug]))


def test_duplicate_slugs_are_rejected():
    with pytest.raises(release.ReleaseError, match="Duplicate"):
        release.validate_manifest(manifest(["ticket", "ticket"]))


def test_reconcile_recovers_completed_publication_before_generation(
    tmp_path, monkeypatch
):
    prior = manifest([], "100")
    current = manifest(["route-delivery"], "101")
    snapshots = iter([prior, current])
    writes = []

    def remote(operation, payload=None):
        if operation == "snapshot":
            return next(snapshots)
        writes.append((operation, payload))

    monkeypatch.setattr(release, "remote", remote)
    monkeypatch.setattr(release, "production_manifest", lambda **kw: current)
    verified = []
    monkeypatch.setattr(
        release, "verify_inventory", lambda new, old: verified.append((new, old))
    )
    target = tmp_path / "baseline.json"
    release.baseline(target)
    assert writes == [("publish", current)]
    assert verified == [(current, prior)]
    assert json.loads(target.read_text()) == current


def test_missing_live_manifest_cannot_reset_existing_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "remote", lambda *_: manifest(["route-delivery"]))
    monkeypatch.setattr(release, "production_manifest", lambda **kw: None)
    with pytest.raises(release.ReleaseError, match="missing"):
        release.baseline(tmp_path / "baseline.json")
    assert not (tmp_path / "baseline.json").exists()


def test_verification_checks_sitemap_and_new_html(monkeypatch):
    old = manifest(["old-page"], "100")
    current = manifest(["old-page", "new-page"], "101")
    monkeypatch.setattr(release, "production_manifest", lambda: current)
    monkeypatch.setattr(
        release, "sitemap_urls", lambda: {release.SITE + "/use-cases/old-page"}
    )
    with pytest.raises(release.ReleaseError, match="sitemap"):
        release.verify_once(current, old)
    monkeypatch.setattr(
        release,
        "sitemap_urls",
        lambda: {release.SITE + "/use-cases/" + p["slug"] for p in current["pages"]},
    )
    monkeypatch.setattr(release, "fetch", lambda _: b"<html>Not found</html>")
    with pytest.raises(release.ReleaseError, match="article"):
        release.verify_once(current, old)


def test_verification_caps_new_pages_per_publication(tmp_path, monkeypatch):
    expected, previous = tmp_path / "next.json", tmp_path / "prior.json"
    release.write_json(expected, manifest([f"case-{i}" for i in range(51)]))
    release.write_json(previous, manifest())
    monkeypatch.setattr(release, "remote", lambda *_: pytest.fail("must not publish"))
    with pytest.raises(release.ReleaseError, match="50 new pages"):
        release.verify(expected, previous, attempts=1)


def test_record_sends_the_released_run_report(tmp_path, monkeypatch):
    manifest_path = tmp_path / "release.json"
    release.write_json(
        manifest_path, manifest() | {"run_id": "local-20260927T100000Z-1"}
    )
    monkeypatch.setattr(release, "ROOT", tmp_path)
    checkpoint = release.checkpoint_for(manifest_path)
    assert (
        checkpoint == tmp_path / "content/use-cases/runs/f3c231d28a2bec680f71a7d4.json"
    )
    writes = []
    monkeypatch.setattr(
        release, "remote", lambda operation, payload: writes.append(payload)
    )
    release.record(manifest_path)
    assert writes == []
    report = {
        "run_id": "local-20260927T100000Z-1",
        "status": "prepared",
        "mode": "review",
    }
    release.write_json(
        checkpoint, {"schema_version": 1, "complete": True, "report": report}
    )
    release.record(manifest_path)
    assert writes == [report]
    release.write_json(checkpoint, {"schema_version": 1, "report": "bad"})
    with pytest.raises(release.ReleaseError, match="checkpoint"):
        release.record(manifest_path)


def test_sitemap_cannot_fetch_an_external_origin(monkeypatch):
    xml = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://elsewhere.test/collect.xml</loc></sitemap></sitemapindex>"""
    monkeypatch.setattr(release, "fetch", lambda _: xml)
    with pytest.raises(release.ReleaseError, match="outside"):
        release.sitemap_urls()
