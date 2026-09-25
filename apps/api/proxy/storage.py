import asyncio
import time
from datetime import UTC, date, datetime, timedelta

import asyncpg

from .config import RETENTION_SECONDS, Policy


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, pool):
        self.pool = pool
        self._policies = {}
        self._policies_until = 0
        self._policy_lock = asyncio.Lock()
        self.retention_seconds = RETENTION_SECONDS

    @classmethod
    async def connect(cls, url):
        pool = await asyncpg.create_pool(
            url,
            min_size=1,
            max_size=5,
            command_timeout=3,
            server_settings={"application_name": "typesafe-proxy"},
        )
        return cls(pool)

    async def close(self):
        await self.pool.close()

    async def lookup_token(self, token_hash):
        row = await self.pool.fetchrow(
            """SELECT tier, expires_at FROM api_client_tokens
               WHERE token_hash=$1 AND revoked_at IS NULL
               AND (expires_at IS NULL OR expires_at > now())""",
            token_hash,
        )
        if row:
            ttl = (
                30
                if row["expires_at"] is None
                else int((row["expires_at"] - datetime.now(UTC)).total_seconds())
            )
            return row["tier"], ttl
        return None

    async def policies(self):
        if time.monotonic() < self._policies_until:
            return self._policies
        async with self._policy_lock:
            if time.monotonic() < self._policies_until:
                return self._policies
            rows = await self.pool.fetch("SELECT * FROM rate_limit_policies")
            policies = {
                row["tier"]: Policy(
                    row["tier"],
                    row["rpm"],
                    row["burst"],
                    row["queue_wait_seconds"],
                    row["queue_size"],
                )
                for row in rows
            }
            if set(policies) != {"anonymous", "free", "paid"}:
                raise RuntimeError("Missing rate limit policies")
            self._policies = policies
            self._policies_until = time.monotonic() + 30
            return policies

    async def write_errors(self, events):
        columns = tuple(events[0])
        await self.pool.executemany(
            "INSERT INTO proxy_error_events ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join(f"${index + 1}" for index in range(len(columns)))
            + ")",
            [tuple(event[key] for key in columns) for event in events],
        )

    async def cleanup(self):
        # Bound each transaction so cleanup cannot monopolize the database during a burst.
        return await self.pool.execute(
            """DELETE FROM proxy_error_events WHERE id IN
               (SELECT id FROM proxy_error_events WHERE created_at < $1
                ORDER BY created_at LIMIT 2000)""",
            datetime.now(UTC) - timedelta(seconds=self.retention_seconds),
        )

    async def record_page_view(self, path: str, visitor_hash: str, now: datetime):
        return await self.pool.fetchrow(
            """INSERT INTO page_views
               (view_date, path, visitor_hash, first_seen_at, last_seen_at, hits)
               VALUES ($1, $2, $3, $4, $4, 1)
               ON CONFLICT (view_date, path, visitor_hash)
               DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at,
                             hits = page_views.hits + 1
               RETURNING view_date, path, first_seen_at, last_seen_at, hits""",
            now.date(),
            path,
            visitor_hash,
            now,
        )

    async def page_view_page(self, start: date, end: date, page: int, page_size: int):
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                total = await connection.fetchval(
                    """SELECT count(*) FROM (
                           SELECT 1 FROM page_views
                           WHERE view_date BETWEEN $1 AND $2
                           GROUP BY view_date, path
                       ) grouped""",
                    start,
                    end,
                )
                rows = await connection.fetch(
                    """SELECT view_date, path, count(*) AS unique_visitors,
                              coalesce(sum(hits), 0) AS total_hits,
                              min(first_seen_at) AS first_seen_at,
                              max(last_seen_at) AS last_seen_at
                       FROM page_views
                       WHERE view_date BETWEEN $1 AND $2
                       GROUP BY view_date, path
                       ORDER BY view_date DESC, unique_visitors DESC, total_hits DESC, path
                       LIMIT $3 OFFSET $4""",
                    start,
                    end,
                    page_size,
                    (page - 1) * page_size,
                )
        return {
            "items": [
                {
                    "date": row["view_date"].isoformat(),
                    "path": row["path"],
                    "unique_visitors": row["unique_visitors"],
                    "total_hits": row["total_hits"],
                    "first_seen_at": iso(row["first_seen_at"]),
                    "last_seen_at": iso(row["last_seen_at"]),
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "from": start.isoformat(),
            "to": end.isoformat(),
        }

    async def error_page(self, page, page_size, status=None, error_code=None):
        args = [datetime.now(UTC) - timedelta(seconds=self.retention_seconds)]
        conditions = ["created_at >= $1"]
        for column, value in (("status", status), ("error_code", error_code)):
            if value is not None:
                args.append(value)
                conditions.append(f"{column} = ${len(args)}")
        where = " AND ".join(conditions)
        # One snapshot keeps the count and page consistent during concurrent writes/cleanup.
        async with self.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                total = await connection.fetchval(
                    "SELECT count(*) FROM proxy_error_events WHERE " + where, *args
                )
                rows = await connection.fetch(
                    "SELECT * FROM proxy_error_events WHERE "
                    + where
                    + f" ORDER BY created_at DESC, id DESC LIMIT ${len(args) + 1}"
                    + f" OFFSET ${len(args) + 2}",
                    *args,
                    page_size,
                    (page - 1) * page_size,
                )
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
