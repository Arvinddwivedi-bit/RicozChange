"""calendar token

Revision ID: d4a5b6c7e8f9
Revises: c9f8e7d6a5b4
Create Date: 2026-09-27

Adds users.calendar_token — a personal, rotatable token that authenticates the
read-only .ics calendar feed (GET /api/calendar/changes.ics?token=...).
Nullable: users without a token simply have no feed URL.

Idempotent/inspect-first like previous migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a5b6c7e8f9"
down_revision = "c9f8e7d6a5b4"
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

    if "calendar_token" not in _columns(insp, "users"):
        op.add_column("users", sa.Column("calendar_token", sa.String(length=80), nullable=True))
        op.create_index("ix_users_calendar_token", "users", ["calendar_token"])

    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_calendar_token" not in existing_ucs:
            op.create_unique_constraint("uq_users_calendar_token", "users", ["calendar_token"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "users" not in insp.get_table_names():
        return
    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_calendar_token" in existing_ucs:
            op.drop_constraint("uq_users_calendar_token", "users", type_="unique")
    if "ix_users_calendar_token" in _indexes(insp, "users"):
        op.drop_index("ix_users_calendar_token", table_name="users")
    if "calendar_token" in _columns(insp, "users"):
        op.drop_column("users", "calendar_token")
