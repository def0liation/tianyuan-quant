import sqlite3
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.backup import backup_sqlite, restore_sqlite


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_alembic_baseline_upgrades_empty_sqlite_database(tmp_path):
    db_path = tmp_path / "migration_test.db"
    app_logger = logging.getLogger("app.core.market_data_runner")
    app_logger.disabled = False
    config = Config(str(_backend_root() / "alembic.ini"))
    config.set_main_option("script_location", str(_backend_root() / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        version = conn.execute("select version_num from alembic_version").fetchone()[0]

    assert version == "0002_analysis_jobs"
    assert app_logger.disabled is False
    assert {
        "analysis_runs",
        "analysis_jobs",
        "audit_logs",
        "knowledge_versions",
        "backtest_runs",
        "research_loops",
    }.issubset(tables)


def test_sqlite_backup_restore_manifest_and_dry_run(tmp_path):
    source = tmp_path / "source.db"
    backup_dir = tmp_path / "backups"
    restored = tmp_path / "restored.db"
    with sqlite3.connect(source) as conn:
        conn.execute("create table sample (id integer primary key, name text not null)")
        conn.execute("insert into sample (name) values ('alpha')")
        conn.commit()

    backup = backup_sqlite(source, backup_dir, label="unit")
    backup_file = Path(backup["backup_file"])
    manifest_file = Path(backup["manifest_file"])

    assert backup_file.exists()
    assert manifest_file.exists()
    assert backup["sqlite_integrity_check"] == "ok"
    assert backup["sha256"]

    dry_run = restore_sqlite(backup_file, restored, dry_run=True)
    assert dry_run["restored"] is False
    assert dry_run["integrity"] == "ok"

    result = restore_sqlite(backup_file, restored)
    assert result["restored"] is True
    with sqlite3.connect(restored) as conn:
        row = conn.execute("select name from sample where id = 1").fetchone()
    assert row == ("alpha",)
