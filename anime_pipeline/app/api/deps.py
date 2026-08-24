"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.security import InvalidTokenError
from app.db.models import User, Workspace
from app.services.auth.auth_service import AuthService
from app.services.workspaces.workspace_service import (
    InsufficientRoleError,
    NotAMemberError,
    WorkspaceService,
)


def db_session() -> Iterator[Session]:
    yield from get_session()


def current_user(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(db_session),
) -> User:
    """Resolve the bearer token to a user, or 401.

    Every failure returns the same status and a generic detail. Saying which
    part of the token was wrong tells a forger which half to keep working on.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        return AuthService(session).user_from_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def resolve_workspace(
    workspace_slug: str,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> Workspace:
    """The workspace, if this user may see it.

    A workspace the caller is not a member of returns 404, not 403. A 403 would
    confirm that the slug exists, which is itself information the caller has no
    right to.
    """
    service = WorkspaceService(session)
    workspace = service.by_slug(workspace_slug)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown workspace {workspace_slug!r}"
        )
    try:
        service.require_member(workspace=workspace, user=user)
    except NotAMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown workspace {workspace_slug!r}"
        ) from exc
    return workspace


def require_workspace_role(required_role: str):
    """Dependency factory gating an endpoint behind a minimum role."""

    def _dependency(
        workspace: Workspace = Depends(resolve_workspace),
        session: Session = Depends(db_session),
        user: User = Depends(current_user),
    ) -> Workspace:
        try:
            WorkspaceService(session).require_role(
                workspace=workspace, user=user, required_role=required_role
            )
        except InsufficientRoleError as exc:
            # 403 here, unlike resolve_workspace: membership is already
            # established, so the caller knowing the workspace exists is not a
            # leak -- and a 404 would be actively confusing.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return workspace

    return _dependency
