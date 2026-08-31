"""Registration, login, and the current identity."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.db.models import User
from app.services.auth.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)

router = APIRouter()

#: Short enough not to annoy, long enough to matter. Length is the only
#: requirement: composition rules push people toward `Passw0rd!` and no further.
MIN_PASSWORD_LENGTH = 12


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool


def _user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def register(body: RegisterRequest, session: Session = Depends(db_session)):
    """Create an account. The first account created becomes the superuser."""
    service = AuthService(session)
    try:
        user = service.register(
            email=body.email, full_name=body.full_name, password=body.password
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return _user_payload(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(db_session)):
    service = AuthService(session)
    try:
        user = service.authenticate(email=body.email, password=body.password)
    except InvalidCredentialsError as exc:
        # 401 with an identical message for unknown email, wrong password and
        # deactivated account -- see InvalidCredentialsError.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    token = service.issue_token(user)
    session.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": service.token_ttl_minutes,
    }


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return _user_payload(user)
