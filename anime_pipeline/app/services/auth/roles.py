"""Workspace roles, ordered by authority.

An ordered ladder rather than a permission matrix. With four roles and a
handful of gated actions, a matrix is more machinery than the problem needs;
if roles ever stop being strictly ordered -- a "billing" role that can pay but
not publish -- this must become a matrix rather than gain a special case.
"""

from __future__ import annotations

OWNER = "owner"
EDITOR = "editor"
MEMBER = "member"
VIEWER = "viewer"

#: Higher outranks lower.
ROLE_RANK = {VIEWER: 10, MEMBER: 20, EDITOR: 30, OWNER: 40}
VALID_ROLES = frozenset(ROLE_RANK)

#: The two irreversible acts. Both require EDITOR: approving a retcon rewrites
#: settled canon, and publishing cannot be taken back once viewers have seen it.
ACTION_APPROVE_RETCON = EDITOR
ACTION_PUBLISH = EDITOR
ACTION_MANAGE_MEMBERS = OWNER


def rank(role: str) -> int:
    return ROLE_RANK.get(role, 0)


def allows(role: str, required_role: str) -> bool:
    """Whether `role` is at least `required_role`.

    An unknown role ranks 0 and therefore permits nothing -- a typo in a role
    name fails closed rather than granting owner.
    """
    return rank(role) >= rank(required_role)
