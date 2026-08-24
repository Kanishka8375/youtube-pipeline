"""The append-only record of who did what."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.request_context import current_correlation_id
from app.db.models import AuditLog, User, Workspace

# Actions worth being able to reconstruct later. Not an exhaustive list of
# everything the API does -- an audit log that records reads is a log nobody
# can find the writes in.
ACTION_RETCON_APPROVED = "retcon.approved"
ACTION_RETCON_REJECTED = "retcon.rejected"
ACTION_EPISODE_PUBLISHED = "episode.published"
ACTION_MEMBER_ADDED = "workspace.member_added"
ACTION_GENERATION_DISPATCHED = "generation.dispatched"


class AuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        actor: Optional[User] = None,
        workspace: Optional[Workspace] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """Append one entry. Never updates, never deletes.

        The correlation id is read from the request context rather than passed
        in, so a caller cannot forget it and leave an entry that cannot be tied
        back to the request that caused it.
        """
        entry = AuditLog(
            actor_user_id=actor.id if actor else None,
            workspace_id=workspace.id if workspace else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
            correlation_id=current_correlation_id(),
            message=message,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def for_workspace(self, workspace_id: uuid.UUID, *, limit: int = 100) -> Sequence[AuditLog]:
        return self.session.scalars(
            select(AuditLog)
            .where(AuditLog.workspace_id == workspace_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        ).all()

    def for_entity(self, entity_type: str, entity_id: str) -> Sequence[AuditLog]:
        return self.session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at)
        ).all()
