"""R6-10: the ``tenancy`` bounded context's MCP server (ADR-011, design
§4.1/§0.5). Two ``READ`` tools, and no others -- design §0's own
assumption 5 is explicit: "tenancy's MCP server is read-only... its
server exposes reads only, and no agent toolset includes it." There is
no tool here that creates a tenant, grants a membership or changes a
setting; this unit's own acceptance test asserts that on the
registered tool list, not by inspection.

Backed by ``cairn_modules.projects`` ("projects service" in design
§4.1's own table) -- ADR-011 names the bounded context ``tenancy``, R1-
01 built it as ``cairn_modules.projects``; one server, two names for
the same thing. ``InMemoryProjectRepository`` enforces tenant isolation
itself, through the ambient ``TenantContext`` (ADR-012) rather than an
argument comparison this server would have to invent -- so every tool
here binds a ``TenantContext`` before calling the repository, and lets
the repository's own, already-proven isolation do the rest (the same
mechanism ``packages/kernel/tests/test_tenancy_isolation.py`` and R1-
01's own tests already exercise -- this server adds no new
tenant-isolation code, it reuses the existing one).

**ADR-020 fix:** that ``TenantContext`` is now built from the
gateway's propagated, authenticated ``Principal`` (``tenant_id``,
``actor_id=principal.subject``, ``actor_roles=principal.role_values()``)
rather than from the caller-supplied ``tenant_id`` argument and a fixed
placeholder ``actor_id="mcp-caller"``. The caller-supplied ``tenant_id``
argument is still required to match the principal's own, so a
mismatched claim fails loudly before the repository is ever reached.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from cairn_kernel.errors import TenantScopeViolationError, ValidationError
from cairn_kernel.hex import ProjectId
from cairn_kernel.security import Principal
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.projects.ports import ProjectRepository
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

TENANCY_CONTEXT_ID = "tenancy"

TOOL_GET_PROJECT = "tenancy.get_project"
TOOL_LIST_PROJECT_MEMBERS = "tenancy.list_project_members"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _GetProjectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str


class _ListMembersArgs(_GetProjectArgs):
    model_config = ConfigDict(extra="forbid")


def _parse(model_cls: type[_ArgsT], arguments: Mapping[str, object]) -> _ArgsT:
    try:
        return model_cls.model_validate(dict(arguments))
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _scope(principal: Principal) -> TenantContext:
    return TenantContext(
        tenant_id=principal.tenant_id,
        project_id=None,
        actor_id=principal.subject,
        actor_roles=principal.role_values(),
        correlation_id=f"mcp-tenancy-{principal.tenant_id.value}",
    )


def _require_caller_matches_principal(caller_tenant_id: str, principal: Principal) -> None:
    if caller_tenant_id != principal.tenant_id.value:
        raise TenantScopeViolationError(
            f"caller-supplied tenant_id {caller_tenant_id!r} does not match the"
            f" authenticated principal's tenant {principal.tenant_id.value!r}"
        )


def build_tenancy_server(repository: ProjectRepository) -> BoundedContextServer:
    """Build the tenancy bounded-context's MCP server, backed by
    ``repository`` -- the same ``ProjectRepository`` ``apps/api``'s own
    project routes already use.
    """

    def handle(tool_name: str, arguments: Mapping[str, object], principal: Principal) -> object:
        if tool_name == TOOL_GET_PROJECT:
            args = _parse(_GetProjectArgs, arguments)
            _require_caller_matches_principal(args.tenant_id, principal)
            with tenant_scope(_scope(principal)):
                return repository.get_project(ProjectId(args.project_id))

        if tool_name == TOOL_LIST_PROJECT_MEMBERS:
            args = _parse(_ListMembersArgs, arguments)
            _require_caller_matches_principal(args.tenant_id, principal)
            with tenant_scope(_scope(principal)):
                return repository.list_members(ProjectId(args.project_id))

        raise ValidationError(f"tenancy MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=TENANCY_CONTEXT_ID,
        name="tenancy",
        tools=(TOOL_GET_PROJECT, TOOL_LIST_PROJECT_MEMBERS),
        capabilities={
            TOOL_GET_PROJECT: ToolCapability.READ,
            TOOL_LIST_PROJECT_MEMBERS: ToolCapability.READ,
        },
        handle=handle,
    )


__all__ = [
    "TENANCY_CONTEXT_ID",
    "TOOL_GET_PROJECT",
    "TOOL_LIST_PROJECT_MEMBERS",
    "build_tenancy_server",
]
