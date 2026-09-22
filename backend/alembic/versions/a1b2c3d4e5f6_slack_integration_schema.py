"""slack integration schema

Revision ID: a1b2c3d4e5f6
Revises: d8013b0b6b62
Create Date: 2026-09-22

Adds Slack integration columns: users.slack_id (identity mapping), notification
delivery audit columns (sent_at, slack_channel, slack_ts, delivery_error), and
the settings table for integration credentials (Slack bot token).

SQLite-safe: SQLite cannot ALTER TABLE ADD CONSTRAINT, so the UNIQUE constraint
on users.slack_id is created only on PostgreSQL (SQLite databases get the index;
fresh SQLite schemas get the constraint from create_all via the models).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision = "d8013b0b6b62"
branch_labels: Union[str, Sequence[str]] | None = None
depends_on: Union[str, Sequence[str]] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column("users", sa.Column("slack_id", sa.String(length=40), nullable=True))
    if _is_postgres():
        op.create_unique_constraint("uq_users_slack_id", "users", ["slack_id"])
    op.create_index("ix_users_slack_id", "users", ["slack_id"])

    op.add_column("notifications", sa.Column("sent_at", sa.DateTime(), nullable=True))
    op.add_column("notifications", sa.Column("slack_channel", sa.String(length=40), nullable=True))
    op.add_column("notifications", sa.Column("slack_ts", sa.String(length=40), nullable=True))
    op.add_column("notifications", sa.Column("delivery_error", sa.Text(), nullable=True))

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_column("notifications", "delivery_error")
    op.drop_column("notifications", "slack_ts")
    op.drop_column("notifications", "slack_channel")
    op.drop_column("notifications", "sent_at")
    op.drop_index("ix_users_slack_id", table_name="users")
    if _is_postgres():
        op.drop_constraint("uq_users_slack_id", "users", type_="unique")
    op.drop_column("users", "slack_id")
