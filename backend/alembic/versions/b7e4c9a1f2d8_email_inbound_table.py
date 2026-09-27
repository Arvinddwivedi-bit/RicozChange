"""email inbound table

Revision ID: b7e4c9a1f2d8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-27

Creates the `email_inbound` table for the email-to-change pipeline (phase 2,
week 3): one row per processed inbound email, with Message-ID dedupe
(unique message_id), the change it produced (parsed_change_id) or the reason
nothing was filed (status + error_detail).

Idempotent/inspect-first like the Slack migration, so it converges from any
starting state (e.g. a database where create_all raced ahead of migrations).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7e4c9a1f2d8"
down_revision = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str]] | None = None
depends_on: Union[str, Sequence[str]] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "email_inbound" in insp.get_table_names():
        return  # converge: table already exists (create_all raced ahead)

    op.create_table(
        "email_inbound",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=500), nullable=False),
        sa.Column("from_addr", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parsed_change_id", sa.Integer(), sa.ForeignKey("changes.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_email_inbound_message_id", "email_inbound", ["message_id"], unique=True)
    op.create_index("ix_email_inbound_from_addr", "email_inbound", ["from_addr"])
    op.create_index("ix_email_inbound_received_at", "email_inbound", ["received_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "email_inbound" not in insp.get_table_names():
        return
    op.drop_table("email_inbound")
