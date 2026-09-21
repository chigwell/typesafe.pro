import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from .config import TIERS


class Rejected(Exception):
    def __init__(self, code, status=503, retry=1):
        self.code, self.status, self.retry = code, status, retry
        super().__init__(code)


class BodyBudget:
    def __init__(self, settings):
        self.settings = settings
        self.bytes = 0
        self.requests = 0

    def enter(self):
        if self.requests >= self.settings.max_pending:
            raise Rejected("queue_full")
        self.requests += 1

    def grow(self, size):
        # Account for bytearray-to-bytes conversion while both copies coexist.
        if self.bytes + 2 * size > self.settings.queue_memory_bytes:
            raise Rejected("queue_full")
        self.bytes += 2 * size

    def leave(self, size):
        self.bytes -= 2 * size
        self.requests -= 1


@dataclass(eq=False)
class Ticket:
    future: asyncio.Future
    deadline: float
    owner: str


class Scheduler:
    def __init__(self, limiter, settings):
        self.limiter = limiter
        self.settings = settings
        self.queues = {tier: deque() for tier in TIERS}
        self.changed = asyncio.Event()
        self.inflight = 0
        self.closed = False
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.run())

    async def close(self):
        self.closed = True
        self.changed.set()
        if self.task:
            await self.task
        for queue in self.queues.values():
            for ticket in queue:
                if not ticket.future.done():
                    ticket.future.set_exception(Rejected("limiter_unavailable"))
            queue.clear()

    async def acquire(self, policy):
        if self.closed:
            raise Rejected("limiter_unavailable")
        queue = self.queues[policy.tier]
        if len(queue) >= policy.queue_size:
            raise Rejected("queue_full")
        future = asyncio.get_running_loop().create_future()
        ticket = Ticket(future, time.monotonic() + policy.queue_wait, uuid4().hex)
        queue.append(ticket)
        self.changed.set()
        try:
            async with asyncio.timeout(policy.queue_wait):
                return await asyncio.shield(future)
        except (TimeoutError, asyncio.CancelledError) as error:
            if future.done() and not future.cancelled() and future.exception() is None:
                await self.release(*future.result())
            else:
                future.cancel()
            if isinstance(error, TimeoutError):
                raise Rejected("queue_timeout", 429) from None
            raise
        finally:
            with contextlib.suppress(ValueError):
                queue.remove(ticket)
            self.changed.set()

    async def release(self, master, owner):
        try:
            await self.limiter.release(master, owner)
        finally:
            self.inflight -= 1
            self.changed.set()

    async def run(self):
        while not self.closed:
            self.changed.clear()
            ticket = None
            for queue in self.queues.values():
                while queue and (queue[0].future.done() or queue[0].deadline <= time.monotonic()):
                    old = queue.popleft()
                    if not old.future.done():
                        old.future.set_exception(Rejected("queue_timeout", 429))
                if queue:
                    ticket = queue[0]
                    break
            if ticket and self.inflight < self.settings.max_inflight:
                try:
                    master = await self.limiter.acquire(ticket.owner)
                    if master:
                        if ticket.future.done():
                            await self.limiter.release(master, ticket.owner)
                        else:
                            self.inflight += 1
                            ticket.future.set_result((master, ticket.owner))
                        continue
                except Exception:
                    if not ticket.future.done():
                        ticket.future.set_exception(Rejected("limiter_unavailable"))
                    continue
            try:
                # Poll only with a backlog; completions and new arrivals wake us immediately.
                async with asyncio.timeout(0.05 if ticket else None):
                    await self.changed.wait()
            except TimeoutError:
                pass
