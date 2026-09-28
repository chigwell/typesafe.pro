"""Use-case content: Postgres queries, a small in-process response cache, preview tokens."""

import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime

from .auth import digest
from .storage import iso
from .use_case_schema import Page

CONTENT_LOCK = 1415131217  # Distinct from the SEO journal lock (1415131216).
SITEMAP_CHUNK = 10_000
MAX_TAGS = 8
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ContentError(ValueError):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def fingerprint(page) -> str:
    """Same definition as the generator's catalog fingerprint (problem/input/decision/action)."""
    keys = ("problem", "input_description", "decision", "action")
    parts = [normalized(getattr(page, key)) for key in keys]
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def slugify(value: str, limit: int = 48) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.lower()))[:limit].strip("-")


def question_types(page: Page) -> list[str]:
    kinds = {question.type for question in page.examples[0].request.questions.values()}
    return sorted(kinds)


def preview_token(secret: bytes, slug: str, ttl: int = 7200, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + ttl)
    signature = digest(secret, f"{slug}.{expires}".encode(), "use-case-preview")
    return f"{expires}.{signature}"


def valid_preview(secret: bytes, slug: str, token: str, now: float | None = None) -> bool:
    try:
        expires, signature = token.split(".", 1)
        if int(expires) < (time.time() if now is None else now):
            return False
    except (ValueError, AttributeError):
        return False
    expected = digest(secret, f"{slug}.{expires}".encode(), "use-case-preview")
    return hmac.compare_digest(signature.encode(), expected.encode())


class ResponseCache:
    """Bounded TTL cache of serialized public responses; cleared on every content write."""

    def __init__(self, ttl=60, limit=2000):
        self.ttl = ttl
        self.limit = limit
        self.items: dict = {}
        self.version = 0

    def get(self, key):
        item = self.items.get(key)
        if item and item[0] > time.monotonic() and item[1] == self.version:
            return item[2]
        return None

    def put(self, key, value):
        if len(self.items) >= self.limit:
            self.items.clear()
        self.items[key] = (time.monotonic() + self.ttl, self.version, value)

    def invalidate(self):
        self.version += 1
        self.items.clear()


CARD_COLUMNS = """u.id, u.slug, u.title, u.summary, u.industry, u.audience, u.task_type,
    u.question_types, u.has_demo, u.published_at, u.updated_at, u.created_at,
    c.slug AS category_slug, c.name AS category_name"""


def card(row, tags) -> dict:
    return {
        "slug": row["slug"],
        "title": row["title"],
        "summary": row["summary"],
        "industry": row["industry"],
        "audience": row["audience"],
        "task_type": row["task_type"],
        "question_types": list(row["question_types"]),
        "has_demo": row["has_demo"],
        "category": (
            {"slug": row["category_slug"], "name": row["category_name"]}
            if row["category_slug"]
            else None
        ),
        "tags": tags.get(row["id"], []),
        "published_at": iso(row["published_at"]) if row["published_at"] else None,
        "updated_at": iso(row["updated_at"]),
    }


class ContentStore:
    def __init__(self, store):
        self.pool = store.pool

    async def _tags_for(self, conn, ids) -> dict:
        if not ids:
            return {}
        rows = await conn.fetch(
            """SELECT l.use_case_id, t.slug, t.name FROM use_case_tag_links l
               JOIN use_case_tags t ON t.id = l.tag_id
               WHERE l.use_case_id = ANY($1::bigint[]) ORDER BY t.slug""",
            ids,
        )
        tags: dict = {}
        for row in rows:
            item = {"slug": row["slug"], "name": row["name"]}
            tags.setdefault(row["use_case_id"], []).append(item)
        return tags

    # ----- public reads ----------------------------------------------------------------

    async def listing(self, *, q=None, category=None, tag=None, page=1, page_size=24) -> dict:
        where = ["u.status = 'published'"]
        args: list = []
        rank = "0"
        if q:
            args.append(q)
            where.append(f"u.search @@ websearch_to_tsquery('english', ${len(args)})")
            rank = f"ts_rank(u.search, websearch_to_tsquery('english', ${len(args)}))"
        if category:
            args.append(category)
            where.append(f"c.slug = ${len(args)}")
        if tag:
            args.append(tag)
            where.append(
                f"""EXISTS (SELECT 1 FROM use_case_tag_links l JOIN use_case_tags t
                    ON t.id = l.tag_id WHERE l.use_case_id = u.id AND t.slug = ${len(args)})"""
            )
        clause = " AND ".join(where)
        base = (
            "FROM use_cases u LEFT JOIN use_case_categories c ON c.id = u.category_id "
            f"WHERE {clause}"
        )
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                total = await conn.fetchval(f"SELECT count(*) {base}", *args)
                rows = await conn.fetch(
                    f"""SELECT {CARD_COLUMNS}, {rank} AS rank {base}
                        ORDER BY rank DESC, u.published_at DESC, u.id DESC
                        LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}""",
                    *args,
                    page_size,
                    (page - 1) * page_size,
                )
                tags = await self._tags_for(conn, [row["id"] for row in rows])
        return {
            "items": [card(row, tags) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def detail(self, slug, *, include_drafts=False) -> dict | None:
        statuses = ["published", "draft"] if include_drafts else ["published"]
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                row = await conn.fetchrow(
                    f"""SELECT {CARD_COLUMNS}, u.content, u.status, u.category_id
                        FROM use_cases u LEFT JOIN use_case_categories c ON c.id = u.category_id
                        WHERE u.slug = $1 AND u.status = ANY($2::text[])""",
                    slug,
                    statuses,
                )
                if row is None:
                    return None
                related = await conn.fetch(
                    f"""SELECT {CARD_COLUMNS} FROM use_cases u
                        LEFT JOIN use_case_categories c ON c.id = u.category_id
                        WHERE u.status = 'published' AND u.id <> $1
                        ORDER BY (u.task_type = $2) DESC,
                                 (u.category_id IS NOT DISTINCT FROM $3) DESC,
                                 (u.industry = $4) DESC, u.published_at DESC, u.slug
                        LIMIT 3""",
                    row["id"],
                    row["task_type"],
                    row["category_id"],
                    row["industry"],
                )
                tags = await self._tags_for(conn, [row["id"], *(r["id"] for r in related)])
        result = card(row, tags)
        result["status"] = row["status"]
        result["page"] = json.loads(row["content"])
        result["related"] = [card(item, tags) for item in related]
        return result

    async def facets(self) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                categories = await conn.fetch(
                    """SELECT c.slug, c.name, c.description, count(u.id) AS count
                       FROM use_case_categories c LEFT JOIN use_cases u
                         ON u.category_id = c.id AND u.status = 'published'
                       GROUP BY c.id ORDER BY c.sort_order, c.name"""
                )
                tags = await conn.fetch(
                    """SELECT t.slug, t.name, count(*) AS count FROM use_case_tags t
                       JOIN use_case_tag_links l ON l.tag_id = t.id
                       JOIN use_cases u ON u.id = l.use_case_id AND u.status = 'published'
                       GROUP BY t.id ORDER BY count(*) DESC, t.slug LIMIT 50"""
                )
                total = await conn.fetchval(
                    "SELECT count(*) FROM use_cases WHERE status = 'published'"
                )
        return {
            "total": total,
            "categories": [dict(row) for row in categories],
            "tags": [dict(row) for row in tags],
        }

    async def sitemap(self, chunk: int) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                total = await conn.fetchval(
                    "SELECT count(*) FROM use_cases WHERE status = 'published'"
                )
                rows = await conn.fetch(
                    """SELECT slug, updated_at FROM use_cases WHERE status = 'published'
                       ORDER BY published_at, id LIMIT $1 OFFSET $2""",
                    SITEMAP_CHUNK,
                    chunk * SITEMAP_CHUNK,
                )
        return {
            "items": [{"slug": r["slug"], "updated_at": iso(r["updated_at"])} for r in rows],
            "total": total,
            "chunks": max(1, -(-total // SITEMAP_CHUNK)),
            "chunk": chunk,
        }

    # ----- admin reads -----------------------------------------------------------------

    async def compact(self) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT slug, status, fingerprint, content FROM use_cases
               WHERE status <> 'archived' ORDER BY created_at, id"""
        )
        keys = (
            "slug",
            "industry",
            "audience",
            "task_type",
            "search_intent",
            "summary",
            "problem",
            "input_description",
            "decision",
            "action",
        )
        result = []
        for row in rows:
            content = json.loads(row["content"])
            item = {key: content[key] for key in keys}
            item["status"] = row["status"]
            item["fingerprint"] = row["fingerprint"].strip()
            result.append(item)
        return result

    async def drafts(self) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT u.slug, u.content, u.inspiration, u.novelty, u.revision, u.updated_at,
                      c.slug AS category_slug,
                      coalesce((SELECT array_agg(t.slug ORDER BY t.slug) FROM use_case_tag_links l
                                JOIN use_case_tags t ON t.id = l.tag_id
                                WHERE l.use_case_id = u.id), '{}') AS tags
               FROM use_cases u LEFT JOIN use_case_categories c ON c.id = u.category_id
               WHERE u.status = 'draft' ORDER BY u.updated_at"""
        )
        return [
            {
                "slug": r["slug"],
                "page": json.loads(r["content"]),
                "inspiration": json.loads(r["inspiration"]) if r["inspiration"] else None,
                "novelty": r["novelty"],
                "revision": r["revision"],
                "category": r["category_slug"],
                "tags": list(r["tags"]),
                "updated_at": iso(r["updated_at"]),
            }
            for r in rows
        ]

    async def categories(self) -> list[dict]:
        rows = await self.pool.fetch(
            "SELECT slug, name, description FROM use_case_categories ORDER BY sort_order, name"
        )
        return [dict(row) for row in rows]

    async def skips(self) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT fingerprint, slug, summary, task_type, decision, reason, created_at
               FROM use_case_skips ORDER BY created_at"""
        )
        return [
            {
                **dict(row),
                "fingerprint": row["fingerprint"].strip(),
                "created_at": iso(row["created_at"]),
            }
            for row in rows
        ]

    # ----- writes ----------------------------------------------------------------------

    async def upsert(
        self,
        page: Page,
        *,
        status: str,
        category: str | None,
        tags: list[str],
        inspiration: dict | None,
        novelty: float | None,
        published_at: datetime | None = None,
    ) -> dict:
        if status not in ("draft", "published"):
            raise ContentError(422, "status must be draft or published")
        tag_slugs = []
        for tag in tags[:MAX_TAGS]:
            value = slugify(tag)
            if value and value not in tag_slugs:
                tag_slugs.append(value)
        content = page.model_dump(exclude_none=True)
        created = datetime.fromisoformat(page.created_at.replace("Z", "+00:00"))
        updated = datetime.fromisoformat(page.updated_at.replace("Z", "+00:00"))
        print_ = fingerprint(page)
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", CONTENT_LOCK)
            category_id = None
            if category:
                category_id = await conn.fetchval(
                    "SELECT id FROM use_case_categories WHERE slug = $1", category
                )
                if category_id is None:
                    raise ContentError(422, f"unknown category {category}")
            existing = await conn.fetchrow(
                "SELECT id, status, published_at FROM use_cases WHERE slug = $1", page.slug
            )
            clash = await conn.fetchval(
                "SELECT slug FROM use_cases WHERE fingerprint = $1 AND slug <> $2",
                print_,
                page.slug,
            )
            if clash:
                raise ContentError(409, f"same scenario as {clash}")
            if existing and existing["status"] == "published" and status == "draft":
                raise ContentError(409, "a published use case cannot become a draft")
            when = None
            if status == "published":
                when = published_at or (existing["published_at"] if existing else None)
                when = when or datetime.now(UTC)
            values = (
                page.slug,
                status,
                category_id,
                print_,
                page.seo.title,
                page.seo.description,
                page.summary,
                page.industry,
                page.audience,
                page.task_type,
                question_types(page),
                page.demo is not None,
                json.dumps(content),
                json.dumps(inspiration) if inspiration else None,
                novelty,
                created,
                updated,
                when,
            )
            if existing:
                row = await conn.fetchrow(
                    """UPDATE use_cases SET status=$2, category_id=$3, fingerprint=$4, title=$5,
                       meta_description=$6, summary=$7, industry=$8, audience=$9, task_type=$10,
                       question_types=$11, has_demo=$12, content=$13::jsonb,
                       inspiration=coalesce($14::jsonb, inspiration),
                       novelty=coalesce($15, novelty),
                       created_at=$16, updated_at=$17, published_at=$18, revision=revision + 1
                       WHERE slug=$1 RETURNING id, revision""",
                    *values,
                )
            else:
                row = await conn.fetchrow(
                    """INSERT INTO use_cases (slug, status, category_id, fingerprint, title,
                       meta_description, summary, industry, audience, task_type, question_types,
                       has_demo, content, inspiration, novelty, created_at, updated_at,
                       published_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14::jsonb,$15,
                               $16,$17,$18) RETURNING id, revision""",
                    *values,
                )
            await conn.execute("DELETE FROM use_case_tag_links WHERE use_case_id = $1", row["id"])
            for slug in tag_slugs:
                tag_id = await conn.fetchval(
                    """INSERT INTO use_case_tags (slug, name) VALUES ($1, $2)
                       ON CONFLICT (slug) DO UPDATE SET slug = excluded.slug RETURNING id""",
                    slug,
                    slug.replace("-", " "),
                )
                await conn.execute(
                    "INSERT INTO use_case_tag_links (use_case_id, tag_id) VALUES ($1, $2)",
                    row["id"],
                    tag_id,
                )
        return {"slug": page.slug, "status": status, "revision": row["revision"]}

    async def set_status(self, slug: str, status: str) -> dict:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", CONTENT_LOCK)
            row = await conn.fetchrow(
                """UPDATE use_cases SET status = $2::varchar, revision = revision + 1,
                   published_at = CASE WHEN $2::varchar = 'published'
                                       THEN coalesce(published_at, now()) ELSE published_at END
                   WHERE slug = $1 RETURNING slug, status, revision""",
                slug,
                status,
            )
        if row is None:
            raise ContentError(404, "use case not found")
        return dict(row)

    async def add_skip(self, item: dict) -> None:
        await self.pool.execute(
            """INSERT INTO use_case_skips (fingerprint, slug, summary, task_type, decision, reason)
               VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (fingerprint) DO UPDATE SET
               reason = excluded.reason""",
            item["fingerprint"],
            item["slug"][:120],
            item["summary"][:800],
            item["task_type"][:80],
            item["decision"][:800],
            (item.get("reason") or "")[:800],
        )


async def cached(state, key, producer):
    """Serve a cached serialized body, or build, serialize and cache it."""
    cache: ResponseCache = state.content_cache
    body = cache.get(key)
    if body is None:
        value = await producer()
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        cache.put(key, body)
    return body


def new_state(app_state):
    app_state.content_cache = ResponseCache()
