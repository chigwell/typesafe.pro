import asyncio
import time
from datetime import UTC, datetime, timedelta

import asyncpg

from .config import RETENTION_SECONDS, Policy


class Store:
    def __init__(self, pool):
        self.pool = pool
        self._policies = {}
        self._policies_until = 0
        self._policy_lock = asyncio.Lock()

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
            datetime.now(UTC) - timedelta(seconds=RETENTION_SECONDS),
        )
