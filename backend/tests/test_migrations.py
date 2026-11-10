"""Database migration tests: Alembic must build exactly the schema the models describe."""

import os
import sqlite3
import subprocess
import sys

from app.models import Base

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _alembic(args: list[str], database_url: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=database_url, APP_ENV="test")
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)


def test_upgrade_head_creates_every_model_table_and_has_no_drift(tmp_path):
    db_file = tmp_path / "migrated.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    upgrade = _alembic(["upgrade", "head"], url)
    assert upgrade.returncode == 0, upgrade.stderr
    with sqlite3.connect(db_file) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        version = conn.execute("select version_num from alembic_version").fetchone()[0]
    assert tables - {"alembic_version"} == set(Base.metadata.tables)
    assert version == "0001"
    check = _alembic(["check"], url)
    assert check.returncode == 0, check.stdout + check.stderr  # models and migrations are in sync

    downgrade = _alembic(["downgrade", "base"], url)
    assert downgrade.returncode == 0, downgrade.stderr
    with sqlite3.connect(db_file) as conn:
        remaining = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert remaining == {"alembic_version"}


def test_tenant_tables_carry_organisation_foreign_keys():
    tenant_tables = ["memberships", "sessions", "scoring_configs", "competitors", "watchlists", "watchlist_items", "intelligence_reports",
                     "api_keys", "subscriptions", "usage_records", "notifications"]
    for name in tenant_tables:
        table = Base.metadata.tables[name]
        column = table.c.organisation_id
        assert not column.nullable, name
        assert any(fk.column.table.name == "organisations" for fk in column.foreign_keys), name


def test_intelligence_tables_record_data_provenance():
    for name in ("repositories", "developer_profiles", "trend_signals", "opportunities", "change_events", "intelligence_reports"):
        assert "data_source" in Base.metadata.tables[name].c, name
