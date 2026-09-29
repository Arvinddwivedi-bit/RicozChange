"""calendar links

Revision ID: e5f6a7b8c9d0
Revises: d4a5b6c7e8f9
Create Date: 2026-09-27

Creates calendar_links (change <-> Google Calendar event) for two-way sync.
Idempotent/inspect-first like previous migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision = "d4a5b6c7e8f9"
branch_labels: Union[str, Sequence[str]] | None = None
depends_on: Union[str, Sequence[str]] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "calendar_links" in insp.get_table_names():
        return
    op.create_table(
        "calendar_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("changes.id"), nullable=False),
        sa.Column("google_event_id", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_calendar_links_change_id", "calendar_links", ["change_id"], unique=True)
    op.create_index("ix_calendar_links_google_event_id", "calendar_links", ["google_event_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "calendar_links" in insp.get_table_names():
        op.drop_table("calendar_links")
