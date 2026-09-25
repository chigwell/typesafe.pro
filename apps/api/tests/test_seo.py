import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import ENV
from pydantic import ValidationError

from proxy.seo import Manifest, RunReport, SeoJournal

API_DIR = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def manifest(run_id="run-1", minutes=0, slugs=("route-support",)):
    return {
        "schema_version": 1,
        "run_id": run_id,
        "source_sha": "a" * 40,
        "catalog_hash": "b" * 64,
        "generated_at": (NOW + timedelta(minutes=minutes)).isoformat(),
        "pages": [
            {
                "slug": slug,
                "title": slug.replace("-", " ").title(),
                "created_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
            }
            for slug in slugs
        ],
    }


def run_report(run_id="run-1", status="prepared", minutes=0):
    return {
        "run_id": run_id,
        "source_sha": "a" * 40,
        "status": status,
        "reason": None,
        "started_at": (NOW + timedelta(minutes=minutes)).isoformat(),
        "finished_at": (NOW + timedelta(minutes=minutes, seconds=30)).isoformat(),
        "duration_seconds": 30,
        "seed": 42,
        "rounds": 1,
        "api_calls": 12,
        "input_tokens": 300,
        "output_tokens": 150,
        "generated_count": 1,
        "rejected_count": 2,
        "rejections": {"uncertain_novelty": 2},
        "catalog_hash": "b" * 64,
    }


async def test_journal_initial_prepared_failed_and_successful_counts(store):
    journal = SeoJournal(store)
    assert (await journal.snapshot())["pages"] == []
    assert (await journal.summary())["total_pages"] == 0
    await journal.record_run(run_report())
    assert (await journal.summary())["total_pages"] == 0
    first = await journal.publish(manifest(), NOW + timedelta(seconds=40))
    assert first["added_count"] == 1
    assert (await journal.snapshot())["run_id"] == "run-1"
    await journal.record_run(run_report("run-2", "failed", 1))
    summary = await journal.summary()
    assert summary["latest_attempt"]["status"] == "failed"
    assert summary["total_pages"] == summary["added_last_deploy"] == 1
    assert summary["totals"] == {
        "runs": 2,
        "api_calls": 24,
        "input_tokens": 600,
        "output_tokens": 300,
    }
    second = await journal.publish(
        manifest("run-3", 2, ("route-support", "rank-feedback")), NOW + timedelta(minutes=3)
    )
    assert second["added_count"] == 1
    assert (await journal.summary())["total_pages"] == 2


async def test_publish_idempotency_stale_replay_and_rollback(store):
    journal = SeoJournal(store)
    value = manifest()
    first = await journal.publish(value, NOW + timedelta(seconds=30))
    await journal.publish(manifest("run-2", 2, ()), NOW + timedelta(minutes=3))
    # Replaying a known publication never changes current state.
    assert await journal.publish(value) == first
    assert (await journal.snapshot())["run_id"] == "run-2"
    with pytest.raises(ValueError, match="identity conflict"):
        await journal.publish(value | {"catalog_hash": "c" * 64})
    with pytest.raises(ValueError, match="Stale"):
        await journal.publish(manifest("run-old", 1), NOW + timedelta(minutes=4))
    assert (await journal.summary())["total_pages"] == 0
    assert (await journal.summary())["latest_publication"]["removed_count"] == 1
    # Explicit recovery uses a new release identity and generation timestamp.
    await journal.publish(manifest("run-recovery", 4), NOW + timedelta(minutes=5))
    assert (await journal.summary())["total_pages"] == 1


async def test_run_replay_and_prepared_to_failed_update(store):
    journal = SeoJournal(store)
    value = run_report()
    await journal.record_run(value)
    await journal.record_run(value)
    await journal.record_run(
        value
        | {
            "status": "failed",
            "reason": "deploy_failed",
            "finished_at": (NOW + timedelta(minutes=10)).isoformat(),
        }
    )
    assert await journal.record_run(value) == {"run_id": "run-1", "recorded": False}
    assert (await journal.runs(1, 25))["total"] == 1
    assert (await journal.summary())["latest_attempt"]["status"] == "failed"
    with pytest.raises(ValueError, match="identity"):
        await journal.record_run(value | {"source_sha": "c" * 40})
    await journal.publish(manifest())
    published = (await journal.runs(1, 25))["items"][0]
    assert published["status"] == "published"
    assert published["generation_status"] == "failed"


async def test_page_pagination_and_daily_unique_visitors(store):
    journal = SeoJournal(store)
    await journal.publish(manifest(slugs=("route-support", "rank-feedback")))
    await store.record_page_view("/use-cases/route-support", "a" * 64, NOW)
    await store.record_page_view("/use-cases/route-support", "a" * 64, NOW)
    await store.record_page_view("/use-cases/route-support", "b" * 64, NOW + timedelta(days=1))
    await store.record_page_view("/", "c" * 64, NOW)
    first = await journal.pages(1, 1)
    second = await journal.pages(2, 1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["slug"] == "rank-feedback"
    assert first["items"][0]["total_hits"] == 0
    assert second["items"][0]["slug"] == "route-support"
    assert second["items"][0]["unique_visitors"] == 2
    assert second["items"][0]["total_hits"] == 3


async def test_endpoints_authenticated_read_only_and_paginated(client_for):
    def no_upstream(request):
        pytest.fail("SEO admin request reached upstream")

    async with client_for(no_upstream) as client:
        await client.post("/admin/api/auth/login", json={"password": ENV["ADMIN_PASSWORD"]})
        journal = SeoJournal(client.app.state.store)
        await journal.record_run(run_report())
        await journal.publish(manifest())
        summary = await client.get("/admin/api/seo/summary")
        assert summary.status_code == 200
        assert summary.json()["latest_attempt"]["status"] == "published"
        pages = await client.get("/admin/api/seo/pages?page=1&page_size=1")
        assert pages.json()["items"][0]["path"] == "/use-cases/route-support"
        assert pages.headers["cache-control"] == "no-store"
        assert (await client.get("/admin/api/seo/runs?page=2&page_size=1")).json()["items"] == []
        assert (await client.get("/admin/api/seo/pages?page=0")).status_code == 422
        assert (await client.post("/admin/api/seo/publish", json=manifest())).status_code == 404


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "../bad"),
        ("source_sha", "not-a-sha"),
        ("catalog_hash", "bad"),
        ("generated_at", "2026-09-25T12:00:00"),
    ],
)
def test_manifest_rejects_bad_identity_and_naive_timestamp(field, value):
    with pytest.raises(ValidationError):
        Manifest.model_validate(manifest() | {field: value})


def test_manifest_and_report_validation():
    value = manifest()
    value["pages"].append(value["pages"][0])
    with pytest.raises(ValidationError):
        Manifest.model_validate(value)
    with pytest.raises(ValidationError):
        RunReport.model_validate(run_report() | {"api_calls": -1})
    with pytest.raises(ValidationError):
        RunReport.model_validate(run_report() | {"duration_seconds": float("nan")})


async def test_concurrent_publication_is_idempotent(store):
    journal = SeoJournal(store)
    results = await asyncio.gather(journal.publish(manifest()), journal.publish(manifest()))
    assert results[0] == results[1]
    assert await store.pool.fetchval("SELECT count(*) FROM seo_publications") == 1


async def test_cli_stdin_roundtrip_and_safe_errors(store, migrated):
    async def command(action, value=None):
        args = [sys.executable, "-m", "proxy.seo", action]
        if value is not None:
            args += ["--file", "/dev/stdin"]
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=API_DIR,
            env=os.environ | {"DATABASE_URL": migrated},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(
            json.dumps(value).encode() if value is not None else None
        )
        return process.returncode, stdout, stderr

    code, output, _ = await command("snapshot")
    assert code == 0 and json.loads(output)["pages"] == []
    code, output, _ = await command("record-run", run_report())
    assert code == 0 and json.loads(output)["recorded"] is True
    code, output, _ = await command("publish", manifest())
    assert code == 0 and json.loads(output)["added_count"] == 1
    code, output, _ = await command("snapshot")
    assert code == 0 and json.loads(output)["pages"][0]["slug"] == "route-support"
    code, output, error = await command("record-run", run_report() | {"token": "secret-test-token"})
    assert code == 1 and output == b""
    assert b"secret-test-token" not in error
    assert b"SEO journal failed" in error
