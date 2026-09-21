import asyncio
import os
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from redis.asyncio import Redis

from proxy.config import Settings
from proxy.main import create_app
from proxy.storage import Store

ENV = {
    "TYPESAFE_TEST_API_TOKEN_1": "client-one",
    "TYPESAFE_MASTER_API_TOKEN_1": "master-one",
    "TYPESAFE_TEST_API_TOKEN_2": "client-two",
    "TYPESAFE_MASTER_API_TOKEN_2": "master-two",
    "DATABASE_URL": "postgresql://unused",
    "REDIS_URL": "redis://unused",
    "TOKEN_HASH_SECRET": "test-hash-secret-at-least-32-characters",
    "RELEASE_SHA": "test-release",
    "ADMIN_PASSWORD": "test-admin-password-at-least-32-characters",
}


@pytest.fixture(scope="session")
def redis_url(tmp_path_factory):
    if url := os.environ.get("TEST_REDIS_URL"):
        yield url
        return
    executable = shutil.which("redis-server")
    if not executable:
        pytest.fail("Install redis-server or set TEST_REDIS_URL to a dedicated test database")
    directory = tmp_path_factory.mktemp("redis")
    socket = directory / "redis.sock"
    process = subprocess.Popen(
        [
            executable,
            "--port",
            "0",
            "--unixsocket",
            str(socket),
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield f"unix://{socket}?db=0"
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.fail("Install PostgreSQL or set TEST_DATABASE_URL to a dedicated test database")
    directory = tmp_path_factory.mktemp("pg")
    data = directory / "data"
    subprocess.run(
        [initdb, "-D", str(data), "-A", "trust", "-U", "typesafe", "--no-locale"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-l",
            str(directory / "server.log"),
            "-o",
            f"-k {directory} -c listen_addresses=''",
            "-w",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        yield f"postgresql://typesafe@/postgres?host={quote(str(directory), safe='')}"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-w", "stop", "-m", "immediate"],
            check=True,
            stdout=subprocess.DEVNULL,
        )


@pytest.fixture(scope="session")
def migrated(database_url):
    api = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api,
        env=os.environ | {"DATABASE_URL": database_url},
        check=True,
    )
    return database_url


@pytest.fixture
async def redis(redis_url):
    client = Redis.from_url(redis_url, decode_responses=True)
    for _ in range(100):
        try:
            await client.ping()
            break
        except (ConnectionError, OSError):
            await asyncio.sleep(0.01)
        except Exception:
            await asyncio.sleep(0.01)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def store(migrated):
    store = await Store.connect(migrated)
    await store.pool.execute("TRUNCATE api_client_tokens, proxy_error_events")
    await store.pool.execute("""UPDATE rate_limit_policies SET
        rpm = CASE tier WHEN 'anonymous' THEN 30 WHEN 'free' THEN 120 ELSE 1000 END,
        burst = CASE tier WHEN 'anonymous' THEN 5 WHEN 'free' THEN 10 ELSE 20 END,
        queue_wait_seconds = CASE tier WHEN 'anonymous' THEN 3 WHEN 'free' THEN 10 ELSE 30 END,
        queue_size = CASE tier WHEN 'anonymous' THEN 64 WHEN 'free' THEN 128 ELSE 256 END""")
    yield store
    await store.close()


@pytest.fixture
def client_for(store, redis):
    @asynccontextmanager
    async def factory(handler, *, env=None):
        app = create_app(
            Settings.from_env(ENV | (env or {})),
            httpx.MockTransport(handler),
            store=store,
            redis=redis,
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="https://api.typesafe.pro"
            ) as client:
                client.app = app
                yield client

    return factory
