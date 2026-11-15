"""R2-01: PLATFORM_OPERATOR, a platform-level concept (spec 12.1), not a
tenant role.

Spec section 12.1 is explicit: "PLATFORM_OPERATOR (internal) -- Publish
global mapping releases and operate the platform; not a tenant role and
not reachable from tenant APIs." It is deliberately kept out of
``cairn_kernel.security.roles.Role``/``TENANT_ROLES`` -- a principal's
tenant roles (``Role.TENANT_ADMIN`` and so on) say nothing about whether
that principal also operates the platform, and the two checks must never
be confused with one another.

PLATFORM_OPERATOR is a config-driven allowlist of OIDC subject claims:
empty by default, so no deployment grants it to anyone until an operator
explicitly lists a subject in ``CAIRN_PLATFORM_OPERATOR_SUBJECTS``
(comma-separated).

This module holds the allowlist and the pure membership check only --
not the FastAPI dependency itself. ``cairn_kernel`` is a leaf package
(``.importlinter``'s "Kernel and contracts are leaves" contract) with no
declared dependency on FastAPI, exactly like every other kernel module
(``require_roles`` is a plain function too; the ``Depends``-wired glue
that reads ``request.state.principal`` lives in ``cairn_api``, not here).
The actual ``require_platform_operator`` FastAPI dependency is
``cairn_api.security.require_platform_operator`` -- it is this module's
``is_platform_operator`` plus the same "no principal on the request" ->
``UnauthenticatedError`` check every route's local ``get_principal``
already makes.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

PLATFORM_OPERATOR_SUBJECTS_ENV_VAR = "CAIRN_PLATFORM_OPERATOR_SUBJECTS"


def platform_operator_allowlist(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """The configured set of OIDC subject claims holding PLATFORM_OPERATOR.

    Empty unless ``CAIRN_PLATFORM_OPERATOR_SUBJECTS`` is set -- no
    deployment default grants this to anyone.
    """
    source = env if env is not None else os.environ
    raw = source.get(PLATFORM_OPERATOR_SUBJECTS_ENV_VAR, "")
    return frozenset(subject.strip() for subject in raw.split(",") if subject.strip())


def is_platform_operator(subject: str, *, allowlist: Iterable[str] | None = None) -> bool:
    """Whether ``subject`` holds PLATFORM_OPERATOR.

    ``allowlist`` lets a caller (tests, a service that already loaded its
    own config) supply the set explicitly instead of re-reading the
    environment; omit it to use ``platform_operator_allowlist()``.
    """
    allowed = frozenset(allowlist) if allowlist is not None else platform_operator_allowlist()
    return subject in allowed


__all__ = [
    "PLATFORM_OPERATOR_SUBJECTS_ENV_VAR",
    "is_platform_operator",
    "platform_operator_allowlist",
]
