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
    assert "POSTGRES_PASSWORD" not in target.read_text()
    assert "master-one" not in pg.read_text()
    assert target.stat().st_mode & 0o777 == pg.stat().st_mode & 0o777 == 0o600


def test_deploy_shell_syntax():
    for path in (ROOT / "deploy").glob("*.sh"):
        subprocess.run(["bash", "-n", str(path)], check=True)


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
