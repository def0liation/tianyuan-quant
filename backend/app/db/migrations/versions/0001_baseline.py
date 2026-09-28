"""baseline current application schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-20
"""

from alembic import op

from app.db import models, models_backtest, models_case_library, models_research  # noqa: F401
from app.db.session import Base


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
