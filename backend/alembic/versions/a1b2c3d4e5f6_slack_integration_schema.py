"""slack integration schema

Revision ID: a1b2c3d4e5f6
Revises: d8013b0b6b62
Create Date: 2026-09-22

Adds Slack integration columns: users.slack_id (identity mapping), notification
delivery audit columns (sent_at, slack_channel, slack_ts, delivery_error), and
the settings table for integration credentials (Slack bot token).

Defensive/idempotent by design: databases that booted with create_all running
before migrations (the pre-fix startup order) may already have an empty
`settings` table, and partially-applied upgrades leave some columns behind.
Every step inspects first, so this migration converges from any starting state.

SQLite-safe: SQLite cannot ALTER TABLE ADD CONSTRAINT, so the UNIQUE constraint
on users.slack_id is created only on PostgreSQL (SQLite gets the index; fresh
SQLite schemas get the constraint from create_all via the models).
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


def _columns(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(insp, table: str) -> set[str]:
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # --- users.slack_id ---
    if "slack_id" not in _columns(insp, "users"):
        op.add_column("users", sa.Column("slack_id", sa.String(length=40), nullable=True))
    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_slack_id" not in existing_ucs:
            op.create_unique_constraint("uq_users_slack_id", "users", ["slack_id"])
    if "ix_users_slack_id" not in _indexes(insp, "users"):
        op.create_index("ix_users_slack_id", "users", ["slack_id"])

    # --- notifications delivery audit ---
    for name, col in (
        ("sent_at", sa.Column("sent_at", sa.DateTime(), nullable=True)),
        ("slack_channel", sa.Column("slack_channel", sa.String(length=40), nullable=True)),
        ("slack_ts", sa.Column("slack_ts", sa.String(length=40), nullable=True)),
        ("delivery_error", sa.Column("delivery_error", sa.Text(), nullable=True)),
    ):
        if name not in _columns(insp, "notifications"):
            op.add_column("notifications", col)

    # --- settings table ---
    # Any pre-existing settings table can only have been created by create_all
    # racing ahead of migrations (pre-fix boot order) — it is empty by
    # construction, so adopt-by-recreate is safe.
    if "settings" in insp.get_table_names():
        op.drop_table("settings")
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "settings" in insp.get_table_names():
        op.drop_table("settings")
    cols = _columns(insp, "notifications")
    for name in ("delivery_error", "slack_ts", "slack_channel", "sent_at"):
        if name in cols:
            op.drop_column("notifications", name)
    if "ix_users_slack_id" in _indexes(insp, "users"):
        op.drop_index("ix_users_slack_id", table_name="users")
    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_slack_id" in existing_ucs:
            op.drop_constraint("uq_users_slack_id", "users", type_="unique")
    if "slack_id" in _columns(insp, "users"):
        op.drop_column("users", "slack_id")
