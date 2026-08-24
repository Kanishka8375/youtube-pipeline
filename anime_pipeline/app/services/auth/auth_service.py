"""Registration, login, and resolving a bearer token back to a user."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    TokenService,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.db.models import User


class EmailAlreadyRegisteredError(ValueError):
    """Raised when an address already has an account."""


class InvalidCredentialsError(ValueError):
    """Raised for a bad email, a bad password, or a deactivated account.

    One error for all three: distinguishing them turns the login form into an
    account-enumeration oracle.
    """


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        settings = get_settings()
        self.tokens = TokenService(settings.secret_key)
        self.token_ttl_minutes = settings.access_token_expire_minutes

    # -- lookups -------------------------------------------------------------
    def by_email(self, email: str) -> Optional[User]:
        return self.session.scalar(select(User).where(User.email == email.strip().lower()))

    def by_id(self, user_id: uuid.UUID) -> Optional[User]:
        return self.session.get(User, user_id)

    # -- registration --------------------------------------------------------
    def register(self, *, email: str, full_name: str, password: str) -> User:
        normalised = email.strip().lower()
        if self.by_email(normalised) is not None:
            raise EmailAlreadyRegisteredError(f"{normalised} is already registered")

        # The first account is the superuser. Someone has to be able to create
        # the first workspace, and a bootstrap flag beats a seed script that
        # every deployment forgets to run.
        first_user = self.session.scalar(select(User).limit(1)) is None

        user = User(
            email=normalised,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            is_active=True,
            is_superuser=first_user,
        )
        self.session.add(user)
        self.session.flush()
        return user

    # -- login ---------------------------------------------------------------
    def authenticate(self, *, email: str, password: str) -> User:
        user = self.by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Incorrect email or password")
        if not user.is_active:
            raise InvalidCredentialsError("Incorrect email or password")

        # Transparent upgrade: a hash made at a lower iteration count is
        # rewritten on the one occasion the plaintext is legitimately in hand.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self.session.flush()
        return user

    def issue_token(self, user: User) -> str:
        # `sub` is the immutable id, not the email: an address can be changed,
        # and a token keyed on it would silently follow the new owner.
        return self.tokens.encode(
            {"sub": str(user.id), "email": user.email},
            expires_minutes=self.token_ttl_minutes,
        )

    def user_from_token(self, token: str) -> User:
        claims = self.tokens.decode(token)
        try:
            user_id = uuid.UUID(claims["sub"])
        except (KeyError, ValueError) as exc:
            raise InvalidTokenError("Token subject is not a user id") from exc

        user = self.by_id(user_id)
        if user is None:
            # A valid signature over a deleted user. The token outlived the
            # account; treat it as invalid rather than as an anonymous session.
            raise InvalidTokenError("Token subject no longer exists")
        if not user.is_active:
            raise InvalidTokenError("Account is deactivated")
        return user
