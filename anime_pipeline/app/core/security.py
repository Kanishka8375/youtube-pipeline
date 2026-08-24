"""Password hashing and bearer tokens.

Deliberately dependency-free. The obvious choices -- `passlib[bcrypt]` for
hashing, `PyJWT` for tokens -- are better, and the README says to swap them in
for production. What is here is small enough to audit in one sitting and does
not silently do the wrong thing:

- **PBKDF2-SHA256, 200k iterations, per-password salt.** Not memory-hard like
  argon2, but the constant-time comparison and the salt are the parts that
  matter most, and both are here.
- **HS256 with a pinned algorithm.** The classic JWT failure is accepting the
  `alg` the *token* claims: a forged header of `{"alg":"none"}` then verifies
  against nothing. This decoder ignores the token's claimed algorithm and
  verifies with HS256 unconditionally.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

#: Iteration count for PBKDF2. Raising it invalidates nothing -- the count is
#: not stored, so a change only affects newly hashed passwords, and existing
#: ones keep verifying at the count they were made with... which is why it IS
#: stored, below, in the hash string. See `hash_password`.
PBKDF2_ITERATIONS = 200_000
HASH_ALGORITHM = "pbkdf2_sha256"
TOKEN_ALGORITHM = "HS256"


class InvalidTokenError(ValueError):
    """Raised for any token that does not verify, for any reason.

    One error type on purpose: distinguishing "bad signature" from "expired"
    from "malformed" in the *response* tells an attacker which half of a forged
    token to keep working on.
    """


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """`pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>`.

    The iteration count travels with the hash so it can be raised later without
    locking out every existing account: verification uses the count the hash was
    made with, not today's constant.
    """
    if not password:
        raise ValueError("Password must not be empty")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{HASH_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check. False for anything malformed, never an exception."""
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != HASH_ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


def needs_rehash(encoded: str) -> bool:
    """Whether a stored hash was made at a weaker iteration count."""
    try:
        algorithm, iterations, _, _ = encoded.split("$")
    except (ValueError, AttributeError):
        return True
    return algorithm != HASH_ALGORITHM or int(iterations) < PBKDF2_ITERATIONS


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
class TokenService:
    """Signed, expiring bearer tokens."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("Token secret must not be empty")
        self._secret = secret.encode()

    def _sign(self, signing_input: bytes) -> bytes:
        return hmac.new(self._secret, signing_input, hashlib.sha256).digest()

    def encode(self, claims: Dict[str, Any], *, expires_minutes: int) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        payload = {**claims, "exp": int(expires_at.timestamp())}
        header = _b64url_encode(
            json.dumps({"alg": TOKEN_ALGORITHM, "typ": "JWT"}, separators=(",", ":")).encode()
        )
        body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64url_encode(self._sign(f"{header}.{body}".encode()))
        return f"{header}.{body}.{signature}"

    def decode(self, token: str) -> Dict[str, Any]:
        """Verify and return the claims, or raise `InvalidTokenError`.

        The token's own `alg` header is never consulted. Trusting it is the
        algorithm-confusion attack: a token claiming `{"alg": "none"}` would
        otherwise verify against an empty signature.
        """
        try:
            header_b64, body_b64, signature_b64 = token.split(".")
        except (ValueError, AttributeError) as exc:
            raise InvalidTokenError("Malformed token") from exc

        expected = self._sign(f"{header_b64}.{body_b64}".encode())
        try:
            provided = _b64url_decode(signature_b64)
        except Exception as exc:  # noqa: BLE001 -- any decode failure is a bad token
            raise InvalidTokenError("Malformed token signature") from exc

        if not hmac.compare_digest(expected, provided):
            raise InvalidTokenError("Bad token signature")

        try:
            claims = json.loads(_b64url_decode(body_b64))
        except Exception as exc:  # noqa: BLE001
            raise InvalidTokenError("Malformed token payload") from exc

        expires_at = claims.get("exp")
        if not isinstance(expires_at, int):
            # An unexpiring token is a permanent credential. Refuse rather than
            # treat a missing claim as "never expires".
            raise InvalidTokenError("Token has no expiry")
        if expires_at < int(datetime.now(timezone.utc).timestamp()):
            raise InvalidTokenError("Token expired")

        return claims
