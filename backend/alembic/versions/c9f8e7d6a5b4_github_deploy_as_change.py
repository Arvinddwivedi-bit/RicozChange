"""github deploy-as-change schema

Revision ID: c9f8e7d6a5b4
Revises: b7e4c9a1f2d8
Create Date: 2026-09-27

Adds the deploy-as-change schema (v0.3 week 1):
- users.github_login (identity mapping for deployers)
- changes.source ("web" | "email" | "github")
- github_connections (connected repos and their mapping rules)
- github_deliveries (append-only delivery audit + idempotency guard)
- deploy_links (change <-> GitHub run link, carries the deploy conclusion)

Idempotent/inspect-first like previous migrations; safe on SQLite and Postgres
(UNIQUE constraints on nullable columns are index-only on SQLite, full
constraints on Postgres).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9f8e7d6a5b4"
down_revision = "b7e4c9a1f2d8"
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
    tables = insp.get_table_names()

    # --- users.github_login ---
    if "users" in tables and "github_login" not in _columns(insp, "users"):
        op.add_column("users", sa.Column("github_login", sa.String(length=80), nullable=True))
        op.create_index("ix_users_github_login", "users", ["github_login"])

    # --- changes.source ---
    if "changes" in tables and "source" not in _columns(insp, "changes"):
        op.add_column("changes", sa.Column("source", sa.String(length=20), nullable=False, server_default="web"))

    # --- github_connections ---
    if "github_connections" not in tables:
        op.create_table(
            "github_connections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("repo", sa.String(length=200), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("default_system_keys", sa.JSON(), nullable=False),
            sa.Column("default_env", sa.String(length=40), nullable=False, server_default="production"),
            sa.Column("auto_submit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("webhook_secret", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_github_connections_repo", "github_connections", ["repo"], unique=True)

    # --- github_deliveries ---
    if "github_deliveries" not in tables:
        op.create_table(
            "github_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("delivery_id", sa.String(length=120), nullable=False),
            sa.Column("event", sa.String(length=60), nullable=False, server_default=""),
            sa.Column("repo", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("action", sa.String(length=60), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="processed"),
            sa.Column("detail", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("changes.id"), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_github_deliveries_delivery_id", "github_deliveries", ["delivery_id"], unique=True)
        op.create_index("ix_github_deliveries_repo", "github_deliveries", ["repo"])
        op.create_index("ix_github_deliveries_received_at", "github_deliveries", ["received_at"])

    # --- deploy_links ---
    if "deploy_links" not in tables:
        op.create_table(
            "deploy_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("change_id", sa.Integer(), sa.ForeignKey("changes.id"), nullable=False),
            sa.Column("repo", sa.String(length=200), nullable=False),
            sa.Column("run_id", sa.String(length=40), nullable=False),
            sa.Column("run_url", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("head_sha", sa.String(length=60), nullable=False, server_default=""),
            sa.Column("branch", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("environment", sa.String(length=40), nullable=False, server_default="production"),
            sa.Column("conclusion", sa.String(length=30), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_deploy_links_change_id", "deploy_links", ["change_id"])
        op.create_index("ix_deploy_links_repo", "deploy_links", ["repo"])
        op.create_index("ix_deploy_links_run_id", "deploy_links", ["run_id"])

    if _is_postgres():
        existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
        if "github_login" in _columns(insp, "users") and "uq_users_github_login" not in existing_ucs:
            op.create_unique_constraint("uq_users_github_login", "users", ["github_login"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    for t in ("deploy_links", "github_deliveries", "github_connections"):
        if t in tables:
            op.drop_table(t)
    if "changes" in tables and "source" in _columns(insp, "changes"):
        op.drop_column("changes", "source")
    if "users" in tables:
        if _is_postgres():
            existing_ucs = {uc["name"] for uc in insp.get_unique_constraints("users")}
            if "uq_users_github_login" in existing_ucs:
                op.drop_constraint("uq_users_github_login", "users", type_="unique")
        if "ix_users_github_login" in _indexes(insp, "users"):
            op.drop_index("ix_users_github_login", table_name="users")
        if "github_login" in _columns(insp, "users"):
            op.drop_column("users", "github_login")
