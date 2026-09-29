"""teams integration schema

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-29

Adds users.teams_id (identity mapping, same pattern as slack_id) and
notifications.teams_conversation_id / teams_activity_id (delivery audit for
kind="teams" rows, so approve/reject can update the card in place).

Idempotent/inspect-first like previous migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
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

    if "teams_id" not in _columns(insp, "users"):
        op.add_column("users", sa.Column("teams_id", sa.String(length=80), nullable=True))
        op.create_index("ix_users_teams_id", "users", ["teams_id"])

    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_teams_id" not in existing_ucs:
            op.create_unique_constraint("uq_users_teams_id", "users", ["teams_id"])

    for col, name in (
        ("teams_conversation_id", "ix_notifications_teams_conversation_id"),
        ("teams_activity_id", "ix_notifications_teams_activity_id"),
    ):
        if col not in _columns(insp, "notifications"):
            op.add_column("notifications", sa.Column(col, sa.String(length=120), nullable=True))
        if name not in _indexes(insp, "notifications"):
            op.create_index(name, "notifications", [col])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "notifications" in insp.get_table_names():
        for col, name in (
            ("teams_activity_id", "ix_notifications_teams_activity_id"),
            ("teams_conversation_id", "ix_notifications_teams_conversation_id"),
        ):
            if name in _indexes(insp, "notifications"):
                op.drop_index(name, table_name="notifications")
            if col in _columns(insp, "notifications"):
                op.drop_column("notifications", col)

    if "users" not in insp.get_table_names():
        return
    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "uq_users_teams_id" in existing_ucs:
            op.drop_constraint("uq_users_teams_id", "users", type_="unique")
    if "ix_users_teams_id" in _indexes(insp, "users"):
        op.drop_index("ix_users_teams_id", table_name="users")
    if "teams_id" in _columns(insp, "users"):
        op.drop_column("users", "teams_id")
