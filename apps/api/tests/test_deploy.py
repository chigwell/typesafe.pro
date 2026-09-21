import os
import subprocess
import sys
from pathlib import Path

from conftest import ENV

ROOT = Path(__file__).resolve().parents[3]


def test_runtime_environment_files_are_separated_and_private(tmp_path):
    target = tmp_path / "runtime.env"
    subprocess.run(
        [sys.executable, str(ROOT / "deploy/write_env.py"), str(target)],
        env=ENV | {"POSTGRES_PASSWORD": "test-only-db-pass"},
        check=True,
    )
    pg = tmp_path / "postgres.env"
    assert pg.read_text() == "POSTGRES_PASSWORD=test-only-db-pass\n"
    assert "master-one" in target.read_text()
    assert f"ADMIN_PASSWORD={ENV['ADMIN_PASSWORD']}\n" in target.read_text()
    assert "POSTGRES_PASSWORD" not in target.read_text()
    assert "master-one" not in pg.read_text()
    assert target.stat().st_mode & 0o777 == pg.stat().st_mode & 0o777 == 0o600


def test_runtime_environment_derives_internal_urls(tmp_path):
    target = tmp_path / "runtime.env"
    environment = ENV | {"POSTGRES_PASSWORD": "db:/?#[]@!"}
    environment.pop("DATABASE_URL")
    environment.pop("REDIS_URL")
    subprocess.run(
        [sys.executable, str(ROOT / "deploy/write_env.py"), str(target)],
        env=environment,
        check=True,
    )
    values = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert (
        values["DATABASE_URL"]
        == "postgresql://typesafe:db%3A%2F%3F%23%5B%5D%40%21@postgres:5432/typesafe"
    )
    assert values["REDIS_URL"] == "redis://redis:6379/0"


def test_runtime_environment_identifies_missing_postgres_password(tmp_path):
    environment = ENV.copy()
    environment.pop("POSTGRES_PASSWORD", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/write_env.py"), str(tmp_path / "runtime.env")],
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert "POSTGRES_PASSWORD is required" in result.stderr


def test_runtime_environment_requires_admin_password(tmp_path):
    environment = ENV | {"POSTGRES_PASSWORD": "test-only-db-pass"}
    environment.pop("ADMIN_PASSWORD")
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/write_env.py"), str(tmp_path / "runtime.env")],
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0 and "ADMIN_PASSWORD" in result.stderr
    assert not (tmp_path / "runtime.env").exists()


def test_deploy_shell_syntax():
    for path in (ROOT / "deploy").glob("*.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_compose_keeps_the_existing_project_network_for_upgrade():
    compose = (ROOT / "deploy/compose.yml").read_text()
    assert "networks:" not in compose
    assert "TRUSTED_PROXY_CIDRS: 127.0.0.1/32,::1/128,172.16.0.0/12" in compose


def test_migration_is_idempotent(migrated):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "apps/api/alembic.ini"),
            "upgrade",
            "head",
        ],
        env=os.environ | {"DATABASE_URL": migrated},
        check=True,
    )
