from sqlalchemy.orm import Session

from .models import AuditLog


def log_action(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str = "system",
    detail: str = "",
) -> AuditLog:
    """Append an audit entry (flushed, committed with the caller's transaction)."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        detail=detail,
    )
    db.add(entry)
    db.flush()
    return entry
