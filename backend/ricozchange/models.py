from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import UniqueConstraint

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- Reference data ----------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(40), default="engineer")  # admin|manager|approver|engineer
    clerk_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    slack_id: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True, index=True)
    github_login: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True, index=True)
    # Personal, rotatable token for the read-only .ics calendar feed
    # (GET /api/calendar/changes.ics?token=...). None = feed disabled for the user.
    calendar_token: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True, index=True)
    # Teams AAD object id (v0.3 week 3). Same pattern as slack_id: set by email
    # autolink on first Teams action, or by the admin manual-link fallback.
    teams_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemNode(Base):
    """A configuration item (service, database, edge, ...)."""

    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    environment: Mapped[str] = mapped_column(String(40), default="production")  # production|staging|dev
    criticality: Mapped[str] = mapped_column(String(20), default="medium")  # critical|high|medium|low
    owner_team: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DependencyEdge(Base):
    """Directed edge: `source` depends on `target`."""

    __tablename__ = "dependency_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("systems.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("systems.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="depends_on")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FreezeWindow(Base):
    __tablename__ = "freeze_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StandardChangeTemplate(Base):
    __tablename__ = "standard_change_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    icon: Mapped[str] = mapped_column(String(8), default="🔧")
    description: Mapped[str] = mapped_column(Text, default="")
    default_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    checklist: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    rollback_plan: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Change workflow ----------

change_systems = Table(
    "change_systems",
    Base.metadata,
    Column("change_id", ForeignKey("changes.id"), primary_key=True),
    Column("system_id", ForeignKey("systems.id"), primary_key=True),
)


class Change(Base):
    __tablename__ = "changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    risk_type: Mapped[str] = mapped_column(String(20), default="normal")  # standard|normal|major|emergency
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # draft -> submitted -> approved -> implementing -> completed|failed
    # submitted can be rejected; draft/cancelled paths exist too.
    # provenance of this change (web form | email | github deploy)
    source: Mapped[str] = mapped_column(String(20), default="web")

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("standard_change_templates.id"), nullable=True)
    cab_meeting_id: Mapped[int | None] = mapped_column(ForeignKey("cab_meetings.id"), nullable=True)

    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    rollback_plan: Mapped[str] = mapped_column(Text, default="")
    test_plan: Mapped[str] = mapped_column(Text, default="")
    comms_plan: Mapped[str] = mapped_column(Text, default="")

    ai_rollback_draft: Mapped[str] = mapped_column(Text, default="")
    ai_test_draft: Mapped[str] = mapped_column(Text, default="")
    ai_comms_draft: Mapped[str] = mapped_column(Text, default="")

    post_change_result: Mapped[str | None] = mapped_column(String(20), nullable=True)  # success|failed|partial
    post_change_notes: Mapped[str] = mapped_column(Text, default="")
    post_change_prompted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship(lazy="joined")
    systems: Mapped[list[SystemNode]] = relationship(secondary=change_systems, lazy="selectin")
    factors: Mapped[list["RiskFactor"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin", order_by="RiskFactor.id"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="change", cascade="all, delete-orphan", lazy="selectin"
    )


class RiskFactor(Base):
    """One line of the explainable risk score ('why' panel)."""

    __tablename__ = "risk_factors"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    points: Mapped[int] = mapped_column(Integer)  # can be negative (mitigation)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    change: Mapped[Change] = relationship(back_populates="factors")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="web")  # web|slack|cab
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    change: Mapped[Change] = relationship(back_populates="approvals")
    approver: Mapped[User] = relationship(lazy="joined")


class CABMeeting(Base):
    __tablename__ = "cab_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|completed|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items: Mapped[list["CABItem"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="selectin"
    )


class CABItem(Base):
    __tablename__ = "cab_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("cab_meetings.id"), index=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|deferred
    votes: Mapped[list] = mapped_column(JSON, default=list)  # [{voter, vote}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meeting: Mapped[CABMeeting] = relationship(back_populates="items")


class PostChangeResult(Base):
    __tablename__ = "post_change_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    result: Mapped[str] = mapped_column(String(20))  # success|failed|partial
    notes: Mapped[str] = mapped_column(Text, default="")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Cross-cutting ----------

class AuditLog(Base):
    """Append-only audit trail. Never updated, never deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Notification(Base):
    """Demo outbox: what the Slack app *would* send in production."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="slack")  # slack|email
    channel: Mapped[str] = mapped_column(String(120), default="#change-approvals")
    change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id"), nullable=True, index=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[dict] = mapped_column(JSON)  # Slack-blocks-shaped payload
    acted: Mapped[bool] = mapped_column(default=False)
    acted_action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    read: Mapped[bool] = mapped_column(default=False)
    # Real-Slack delivery audit (all None in demo mode)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    slack_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Real-Teams delivery audit (kind="teams" mirror rows): the Bot Framework
    # conversation id + activity id let approve/reject updates edit the card
    # in place (buttons vanish once decided).
    teams_conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teams_activity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    """Key/value integration settings (Slack bot token, signing secret version, ...).
    Values are JSON so a setting can hold structured data without a migration."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ---------- GitHub deploy-as-change (v0.3, week 1) ----------

class GitHubConnection(Base):
    """A connected GitHub repository.

    Production deploy events (workflow_run / deployment) on this repo become
    change requests: scored against `default_system_keys`, filed as drafts (or
    auto-submitted when auto_submit is on and the score is low enough for the
    fast-track), with the deployer mapped by GitHub login or email.
    """

    __tablename__ = "github_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # "owner/name"
    label: Mapped[str] = mapped_column(String(120), default="")
    default_system_keys: Mapped[list] = mapped_column(JSON, default=list)
    default_env: Mapped[str] = mapped_column(String(40), default="production")
    auto_submit: Mapped[bool] = mapped_column(default=False)
    webhook_secret: Mapped[str] = mapped_column(String(200), default="")  # per-connection; falls back to GITHUB_WEBHOOK_SECRET
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GitHubDelivery(Base):
    """Append-only webhook delivery audit + idempotency guard.

    GitHub retries deliveries; the unique delivery_id guarantees an event is
    processed exactly once (same pattern as the email Message-ID dedupe).
    """

    __tablename__ = "github_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event: Mapped[str] = mapped_column(String(60), default="")
    repo: Mapped[str] = mapped_column(String(200), default="", index=True)
    action: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="processed")  # processed|ignored|duplicate|rejected|error
    detail: Mapped[str] = mapped_column(String(300), default="")
    change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class DeployLink(Base):
    """Link between a change and a GitHub deploy run (both directions).

    Created with the change; the workflow_run conclusion lands later and closes
    the outcome loop via record_post_change.
    """

    __tablename__ = "deploy_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), index=True)
    repo: Mapped[str] = mapped_column(String(200), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    run_url: Mapped[str] = mapped_column(String(500), default="")
    head_sha: Mapped[str] = mapped_column(String(60), default="")
    branch: Mapped[str] = mapped_column(String(120), default="")
    environment: Mapped[str] = mapped_column(String(40), default="production")
    conclusion: Mapped[str | None] = mapped_column(String(30), nullable=True)  # success|failure|cancelled|...
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CalendarLink(Base):
    """Link between a change and its Google Calendar event (two-way sync).

    Created on first successful push; the google_event_id lets updates go to
    the same event (PUT) and deletions remove it. Rows are removed when the
    event is deleted.
    """

    __tablename__ = "calendar_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id"), unique=True, index=True)
    google_event_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailInbound(Base):
    """One inbound email processed by the email-to-change pipeline.

    Rows are the delivery/parsing audit: every accepted email records the change
    it produced (status='created') or why nothing was filed (status='rejected'
    with error_detail). message_id is unique so the same email is never filed
    twice (Message-ID dedupe)."""

    __tablename__ = "email_inbound"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    from_addr: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    parsed_change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")  # created|rejected|error
    error_detail: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
