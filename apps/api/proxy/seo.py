"""Private SEO journal commands; run on the server with DATABASE_URL, never over HTTP."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .storage import Store, iso

RunId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")]
SourceSha = Annotated[str, Field(pattern=r"^[a-f0-9]{7,64}$")]
CatalogHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(ge=0, le=10**12)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublishedPage(StrictModel):
    slug: Annotated[str, Field(max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def dates(self):
        if self.updated_at < self.created_at:
            raise ValueError("Page update precedes creation")
        return self


class Manifest(StrictModel):
    schema_version: Literal[1]
    run_id: RunId
    source_sha: SourceSha
    catalog_hash: CatalogHash
    generated_at: AwareDatetime
    pages: list[PublishedPage]

    @model_validator(mode="after")
    def unique_pages(self):
        if len({page.slug for page in self.pages}) != len(self.pages):
            raise ValueError("Duplicate page slugs")
        return self


class RunReport(StrictModel):
    run_id: RunId
    source_sha: SourceSha
    status: Literal["prepared", "skipped", "failed"]
    reason: Annotated[str | None, Field(max_length=1000)] = None
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    seed: int | Annotated[str, Field(max_length=128)]
    rounds: Count
    api_calls: Count
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    generated_count: Count
    rejected_count: Count
    rejections: dict[Annotated[str, Field(max_length=128)], Count]
    catalog_hash: CatalogHash | Literal[""]

    @model_validator(mode="after")
    def dates(self):
        if self.finished_at < self.started_at:
            raise ValueError("Run finish precedes start")
        return self


def publication(row):
    if row is None:
        return None
    return {
        key: iso(value) if isinstance(value, datetime) else value
        for key, value in dict(row).items()
        if key not in ("id", "manifest")
    }


def report(row):
    result = json.loads(row["report"])
    result["generation_status"] = result["status"]
    result["published_at"] = iso(row["published_at"]) if row["published_at"] else None
    if result["published_at"]:
        result["status"] = "published"
    return result


class SeoJournal:
    def __init__(self, store):
        self.pool = store.pool

    async def snapshot(self):
        value = await self.pool.fetchval(
            "SELECT manifest FROM seo_publications ORDER BY id DESC LIMIT 1"
        )
        return (
            json.loads(value)
            if value
            else {
                "schema_version": 1,
                "run_id": "",
                "source_sha": "",
                "catalog_hash": "",
                "generated_at": None,
                "pages": [],
            }
        )

    async def record_run(self, value):
        data = RunReport.model_validate(value)
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(1415131216)")
            existing = await conn.fetchrow("SELECT * FROM seo_runs WHERE run_id=$1", data.run_id)
            if existing and (
                existing["source_sha"] != data.source_sha
                or existing["started_at"] != data.started_at
            ):
                raise ValueError("Run identity conflict")
            if existing and existing["finished_at"] > data.finished_at:
                # A retry can replay the original generation report after a later deploy failure.
                return {"run_id": data.run_id, "recorded": False}
            await conn.execute(
                """INSERT INTO seo_runs
                   (run_id,source_sha,status,started_at,finished_at,report)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                   ON CONFLICT (run_id) DO UPDATE SET
                   status=excluded.status,finished_at=excluded.finished_at,
                   report=excluded.report,recorded_at=now()""",
                data.run_id,
                data.source_sha,
                data.status,
                data.started_at,
                data.finished_at,
                data.model_dump_json(),
            )
        return {"run_id": data.run_id, "recorded": True}

    async def publish(self, value, published_at=None):
        data = Manifest.model_validate(value)
        when = datetime.now(UTC) if published_at is None else published_at
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("Publication timestamp requires timezone")
        if data.generated_at > when:
            raise ValueError("Publication precedes generation")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(1415131216)")
            existing = await conn.fetchrow(
                "SELECT * FROM seo_publications WHERE run_id=$1", data.run_id
            )
            if existing:
                if Manifest.model_validate_json(existing["manifest"]) != data:
                    raise ValueError("Publication run identity conflict")
                return publication(existing)
            latest = await conn.fetchrow("SELECT * FROM seo_publications ORDER BY id DESC LIMIT 1")
            if latest and (
                data.generated_at <= latest["generated_at"] or when <= latest["published_at"]
            ):
                raise ValueError("Stale publication snapshot")
            previous = await conn.fetch("SELECT slug FROM seo_pages")
            previous_slugs = {row["slug"] for row in previous}
            new_slugs = {page.slug for page in data.pages}
            row = await conn.fetchrow(
                """INSERT INTO seo_publications
                   (run_id,source_sha,catalog_hash,generated_at,published_at,
                    added_count,removed_count,total_pages,manifest)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb) RETURNING *""",
                data.run_id,
                data.source_sha,
                data.catalog_hash,
                data.generated_at,
                when,
                len(new_slugs - previous_slugs),
                len(previous_slugs - new_slugs),
                len(data.pages),
                data.model_dump_json(),
            )
            await conn.executemany(
                """INSERT INTO seo_pages (slug,title,created_at,updated_at,published_at)
                   VALUES ($1,$2,$3,$4,$5) ON CONFLICT (slug) DO UPDATE SET
                   title=excluded.title,created_at=excluded.created_at,updated_at=excluded.updated_at""",
                [
                    (page.slug, page.title, page.created_at, page.updated_at, when)
                    for page in data.pages
                ],
            )
            await conn.execute(
                "DELETE FROM seo_pages WHERE NOT (slug = ANY($1::text[]))", list(new_slugs)
            )
        return publication(row)

    async def summary(self):
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                latest = await conn.fetchrow(
                    "SELECT * FROM seo_publications ORDER BY id DESC LIMIT 1"
                )
                attempt = await conn.fetchrow(
                    """SELECT r.report,p.published_at FROM seo_runs r
                       LEFT JOIN seo_publications p USING (run_id)
                       ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1"""
                )
                totals = await conn.fetchrow(
                    """SELECT count(*) AS runs,
                       coalesce(sum((report->>'api_calls')::bigint),0)::bigint AS api_calls,
                       sum((report->>'input_tokens')::bigint)::bigint AS input_tokens,
                       sum((report->>'output_tokens')::bigint)::bigint AS output_tokens
                       FROM seo_runs"""
                )
        return {
            "total_pages": latest["total_pages"] if latest else 0,
            "added_last_deploy": latest["added_count"] if latest else 0,
            "latest_publication": publication(latest),
            "latest_attempt": report(attempt) if attempt else None,
            "totals": dict(totals),
        }

    async def pages(self, page, page_size):
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                total = await conn.fetchval("SELECT count(*) FROM seo_pages")
                rows = await conn.fetch(
                    """SELECT p.*, '/use-cases/' || p.slug AS path,
                       coalesce(v.unique_visitors,0) AS unique_visitors,
                       coalesce(v.total_hits,0)::bigint AS total_hits
                       FROM (SELECT * FROM seo_pages ORDER BY published_at DESC,slug
                             LIMIT $1 OFFSET $2) p
                       LEFT JOIN LATERAL (
                         SELECT count(*) AS unique_visitors,sum(hits) AS total_hits
                         FROM page_views WHERE path='/use-cases/' || p.slug
                       ) v ON true ORDER BY p.published_at DESC,p.slug""",
                    page_size,
                    (page - 1) * page_size,
                )
        return {
            "items": [publication(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def runs(self, page, page_size):
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                total = await conn.fetchval("SELECT count(*) FROM seo_runs")
                rows = await conn.fetch(
                    """SELECT r.report,p.published_at FROM seo_runs r
                       LEFT JOIN seo_publications p USING (run_id)
                       ORDER BY r.started_at DESC,r.run_id DESC LIMIT $1 OFFSET $2""",
                    page_size,
                    (page - 1) * page_size,
                )
        return {
            "items": [report(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def read_input(filename):
    path = Path(filename)
    limit = 100 * 1024 * 1024
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("SEO input exceeds size limit")
    return json.loads(content)


async def run(args):
    store = await Store.connect(os.environ["DATABASE_URL"])
    try:
        journal = SeoJournal(store)
        if args.action == "snapshot":
            result = await journal.snapshot()
        else:
            # Bounded input, and errors must never echo JSON content or secrets from a bad report.
            value = await asyncio.to_thread(read_input, args.file)
            if args.action == "record-run":
                result = await journal.record_run(value)
            else:
                when = datetime.fromisoformat(args.published_at) if args.published_at else None
                result = await journal.publish(value, when)
        print(json.dumps(result))
    finally:
        await store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("snapshot")
    record = commands.add_parser("record-run")
    record.add_argument("--file", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--file", required=True)
    publish.add_argument("--published-at")
    try:
        asyncio.run(run(parser.parse_args()))
    except Exception:
        parser.exit(1, "SEO journal failed; check database availability and input validity.\n")


if __name__ == "__main__":
    main()
