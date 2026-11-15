"""R2-01: ``require_platform_operator``, the FastAPI dependency gating
``POST /v1/mappings/{version}:publish``.

PLATFORM_OPERATOR is a platform-level concept (spec 12.1), not a tenant
role -- it is deliberately kept out of ``cairn_kernel.security.Role``/
``TENANT_ROLES``. ``cairn_kernel`` is a leaf package with no declared
dependency on FastAPI (same as every other kernel module -- ``require_
roles`` is a plain function, not a ``Depends``-wired one), so the actual
``Request``-reading, ``Depends``-compatible dependency lives here in
``cairn_api`` instead, built on
``cairn_kernel.security.platform_operators.is_platform_operator``.

Unlike ``get_principal`` (deliberately duplicated per ``routes_*.py``
file -- see ``routes_projects.py``), this is defined once: a later story
(R2-02) needs to resolve to literally this dependency object, not a copy
that could silently drift from it.
"""

from __future__ import annotations

from cairn_kernel.errors import ForbiddenError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_kernel.security.platform_operators import is_platform_operator
from fastapi import Request


def require_platform_operator(request: Request) -> Principal:
    """The caller must be an authenticated principal whose subject claim
    is in the PLATFORM_OPERATOR allowlist
    (``CAIRN_PLATFORM_OPERATOR_SUBJECTS``, empty by default -- no
    deployment grants this to anyone until an operator explicitly lists a
    subject there).

    Raises ``UnauthenticatedError`` (401) if no principal is on the
    request at all, and ``ForbiddenError`` (403) if the principal is
    authenticated but not a platform operator -- the same two-error split
    every route's local ``get_principal`` already uses for tenant
    authentication.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    if not is_platform_operator(principal.subject):
        raise ForbiddenError("principal is not a platform operator")
    return principal


__all__ = ["require_platform_operator"]
