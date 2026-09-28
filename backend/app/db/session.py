import os
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[3] / "storage" / "tianyuan_quant.db"
if os.environ.get("TIANYUAN_QUANT_DB_URL"):
    DATABASE_URL = os.environ["TIANYUAN_QUANT_DB_URL"]
else:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def create_tables():
    from . import models
    from . import models_case_library
    from . import models_backtest
    from . import models_research
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_migrations():
    if os.getenv("TIANYUAN_SKIP_ALEMBIC", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "TIANYUAN_SKIP_ALEMBIC"}
    try:
        from alembic import command
        from alembic.config import Config

        backend_root = Path(__file__).resolve().parents[2]
        config = Config(str(backend_root / "alembic.ini"))
        config.set_main_option("script_location", str(backend_root / "app" / "db" / "migrations"))
        config.set_main_option("sqlalchemy.url", DATABASE_URL)
        await asyncio.to_thread(command.upgrade, config, "head")
        return {"status": "ok", "revision": "head"}
    except Exception as exc:
        logger.exception("Database migration failed.")
        if os.getenv("APP_ENV") == "production" or os.getenv("REQUIRE_DB_MIGRATIONS") == "1":
            raise
        return {"status": "error", "message": str(exc)}


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
