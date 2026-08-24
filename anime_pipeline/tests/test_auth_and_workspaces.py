"""Authentication, roles, and the boundaries between workspaces."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import (
    InvalidTokenError,
    TokenService,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.db.models import User
from app.services.auth.roles import EDITOR, MEMBER, OWNER, VIEWER, allows
from tests.test_workflow_persistence import fresh_session

PASSWORD = "correct-horse-battery-staple"


def register(client, email, password=PASSWORD, name="Test User"):
    return client.post(
        "/auth/register", json={"email": email, "full_name": name, "password": password}
    )


def login(client, email, password=PASSWORD):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def signed_in(client, email, name="Test User"):
    assert register(client, email, name=name).status_code == 201
    return login(client, email)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def test_a_password_is_never_stored_in_the_clear():
    encoded = hash_password(PASSWORD)
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password(PASSWORD + "x", encoded)


def test_the_same_password_hashes_differently_every_time():
    # Per-password salt: without it, identical passwords share a hash and one
    # rainbow table cracks every account that chose the same weak password.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


@pytest.mark.parametrize("garbage", ["", "not-a-hash", "a$b$c", "pbkdf2_sha256$x$y$z"])
def test_a_malformed_hash_fails_closed(garbage):
    # Returns False rather than raising: a corrupt row must not 500 the login
    # endpoint, and it certainly must not authenticate.
    assert verify_password(PASSWORD, garbage) is False


def test_a_weaker_stored_hash_is_flagged_for_rehash():
    assert needs_rehash("pbkdf2_sha256$1000$aa$bb")
    assert not needs_rehash(hash_password(PASSWORD))


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def test_a_token_round_trips():
    service = TokenService("a-secret")
    token = service.encode({"sub": "user-1"}, expires_minutes=10)
    assert service.decode(token)["sub"] == "user-1"


def test_a_token_signed_with_another_secret_is_rejected():
    token = TokenService("secret-a").encode({"sub": "u"}, expires_minutes=10)
    with pytest.raises(InvalidTokenError):
        TokenService("secret-b").decode(token)


def test_an_alg_none_forgery_is_rejected():
    # The classic JWT break: the decoder trusts the algorithm the *token*
    # names, so a header of {"alg":"none"} verifies against no signature.
    import base64
    import json

    service = TokenService("a-secret")
    real = service.encode({"sub": "u"}, expires_minutes=10)
    body = real.split(".")[1]
    forged_header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    )
    with pytest.raises(InvalidTokenError):
        service.decode(f"{forged_header}.{body}.")


def test_an_expired_token_is_rejected():
    service = TokenService("a-secret")
    with pytest.raises(InvalidTokenError, match="expired"):
        service.decode(service.encode({"sub": "u"}, expires_minutes=-1))


def test_a_token_without_an_expiry_is_rejected():
    # An unexpiring token is a permanent credential. Treating a missing claim
    # as "never expires" is how one leaked token stays valid forever.
    import base64
    import hashlib
    import hmac
    import json

    secret = b"a-secret"
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps({"sub": "u"}).encode()).rstrip(b"=").decode()
    signature = hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

    with pytest.raises(InvalidTokenError, match="no expiry"):
        TokenService("a-secret").decode(forged)


# ---------------------------------------------------------------------------
# Registration and login
# ---------------------------------------------------------------------------
def test_the_first_account_becomes_the_superuser(client):
    first = register(client, "first@studio.example")
    assert first.json()["is_superuser"] is True
    second = register(client, "second@studio.example")
    assert second.json()["is_superuser"] is False


def test_a_duplicate_email_is_rejected(client):
    register(client, "dup@studio.example")
    assert register(client, "dup@studio.example").status_code == 409


def test_a_short_password_is_rejected(client):
    assert register(client, "short@studio.example", password="hunter2").status_code == 422


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    register(client, "real@studio.example")
    wrong = client.post("/auth/login", json={"email": "real@studio.example", "password": "nope"})
    unknown = client.post("/auth/login", json={"email": "ghost@studio.example", "password": "nope"})
    # Identical status *and* body. A different message for a real address turns
    # the login form into an account-enumeration oracle.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_a_deactivated_account_cannot_log_in(client):
    register(client, "gone@studio.example")
    with fresh_session() as session:
        user = session.scalar(select(User).where(User.email == "gone@studio.example"))
        user.is_active = False
        session.commit()
    assert client.post(
        "/auth/login", json={"email": "gone@studio.example", "password": PASSWORD}
    ).status_code == 401


@pytest.mark.parametrize(
    "header",
    [None, "", "garbage", "Bearer", "Bearer not-a-token", "Basic dXNlcjpwYXNz"],
)
def test_every_bad_authorization_header_is_a_401(client, header):
    headers = {} if header is None else {"Authorization": header}
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_me_returns_the_signed_in_user(client):
    headers = signed_in(client, "me@studio.example")
    assert client.get("/auth/me", headers=headers).json()["email"] == "me@studio.example"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "role,required,expected",
    [
        (OWNER, EDITOR, True),
        (EDITOR, EDITOR, True),
        (MEMBER, EDITOR, False),
        (VIEWER, OWNER, False),
        ("typo-role", VIEWER, False),
    ],
)
def test_the_role_ladder_orders_authority(role, required, expected):
    # An unknown role permits nothing: a typo fails closed rather than granting
    # owner by accidentally ranking above it.
    assert allows(role, required) is expected


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------
def test_a_workspace_creator_becomes_its_owner(client):
    headers = signed_in(client, "founder@studio.example")
    workspace = client.post("/workspaces", json={"name": "Neon Veil"}, headers=headers).json()
    members = client.get(f"/workspaces/{workspace['slug']}/members", headers=headers).json()
    assert [(m["email"], m["role"]) for m in members] == [("founder@studio.example", OWNER)]


def test_a_non_member_cannot_see_a_workspace_or_learn_it_exists(client):
    owner = signed_in(client, "owner@studio.example")
    workspace = client.post("/workspaces", json={"name": "Private Studio"}, headers=owner).json()

    stranger = signed_in(client, "stranger@studio.example", name="Stranger")
    # 404 rather than 403: a 403 confirms the slug is real, which is itself
    # information a stranger has no right to.
    assert client.get(f"/workspaces/{workspace['slug']}", headers=stranger).status_code == 404
    assert client.get("/workspaces", headers=stranger).json() == []


def test_only_an_owner_can_change_membership(client):
    owner = signed_in(client, "boss@studio.example")
    workspace = client.post("/workspaces", json={"name": "Studio B"}, headers=owner).json()
    register(client, "viewer@studio.example")
    viewer = login(client, "viewer@studio.example")

    assert client.post(
        f"/workspaces/{workspace['slug']}/members",
        json={"email": "viewer@studio.example", "role": VIEWER},
        headers=owner,
    ).status_code == 201

    escalation = client.post(
        f"/workspaces/{workspace['slug']}/members",
        json={"email": "viewer@studio.example", "role": OWNER},
        headers=viewer,
    )
    assert escalation.status_code == 403


def test_a_duplicate_workspace_name_is_rejected(client):
    headers = signed_in(client, "dup@studio.example")
    assert client.post("/workspaces", json={"name": "Same"}, headers=headers).status_code == 201
    assert client.post("/workspaces", json={"name": "Same"}, headers=headers).status_code == 409


def test_adding_a_member_twice_re_roles_rather_than_duplicating(client):
    owner = signed_in(client, "o2@studio.example")
    workspace = client.post("/workspaces", json={"name": "Studio C"}, headers=owner).json()
    register(client, "m@studio.example")
    for role in (VIEWER, EDITOR):
        client.post(
            f"/workspaces/{workspace['slug']}/members",
            json={"email": "m@studio.example", "role": role},
            headers=owner,
        )
    members = client.get(f"/workspaces/{workspace['slug']}/members", headers=owner).json()
    roles = {m["email"]: m["role"] for m in members}
    assert roles["m@studio.example"] == EDITOR
    assert len(members) == 2


# ---------------------------------------------------------------------------
# Config profiles
# ---------------------------------------------------------------------------
def test_a_credential_is_refused_in_a_config_profile(client):
    headers = signed_in(client, "cfg@studio.example")
    workspace = client.post("/workspaces", json={"name": "Cfg"}, headers=headers).json()
    response = client.put(
        f"/workspaces/{workspace['slug']}/config-profiles",
        json={"profile_key": "llm.default", "profile_json": {"api_key": "sk-leak"}},
        headers=headers,
    )
    assert response.status_code == 400
    assert "api_key" in response.json()["detail"]


def test_provider_settings_are_not_mistaken_for_credentials(client):
    # `provider_key` and `max_tokens` both contain a word that looks secret.
    # A substring check rejects exactly the settings this endpoint exists for.
    headers = signed_in(client, "cfg2@studio.example")
    workspace = client.post("/workspaces", json={"name": "Cfg2"}, headers=headers).json()
    response = client.put(
        f"/workspaces/{workspace['slug']}/config-profiles",
        json={
            "profile_key": "llm.default",
            "profile_json": {"provider_key": "mock", "model": "m", "max_tokens": 16000},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_the_audit_log_records_who_added_whom(client):
    owner = signed_in(client, "audit@studio.example")
    workspace = client.post("/workspaces", json={"name": "Audited"}, headers=owner).json()
    register(client, "newbie@studio.example")
    client.post(
        f"/workspaces/{workspace['slug']}/members",
        json={"email": "newbie@studio.example", "role": MEMBER},
        headers=owner,
    )
    entries = client.get(f"/workspaces/{workspace['slug']}/audit-log", headers=owner).json()
    assert [e["action"] for e in entries] == ["workspace.member_added"]
    assert "newbie@studio.example" in entries[0]["message"]
    # Every entry is tied to the request that caused it.
    assert entries[0]["correlation_id"]
