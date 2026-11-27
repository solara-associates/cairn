"""R6-11: the ``transformation`` bounded context's MCP server (ADR-011,
design §4.1). Six tools: four ``READ`` and two ``PROPOSE``
(``transformation.run``, ``transformation.validate``).

``transformation.run`` invokes the real
``cairn_modules.transformation.engine.TransformationPort`` (the
clean-room Rust engine, ADR-015, through whichever adapter --
real or ``FakeTransformationPort`` -- this server was built with) and
records the resulting manifest through the real
``TransformationRunRepository`` -- "through the existing transformation
service" (design §3.3), not a bespoke persistence path this server
invents. It writes **nothing** outside that repository: the port only
ever reads ``SourceFile.content`` (an in-memory string) and returns a
manifest describing changes; no filesystem path is touched, no
customer repository is written to, and applying a diff anywhere is a
separate Class C operation behind the execution gate this server has
no tool for (design §4.2/§11).

This server keeps the ``SourceFile`` sequence a run was given, in
memory, keyed by the run id ``transformation.run`` returns -- the
repository persists the manifest, not the files it was computed from,
and ``transformation.get_diff``/``transformation.validate`` both need
the originals back to render a diff or build a ``ValidationRequest``
(``cairn_modules.transformation.diff``/``validation`` are both pure
functions over files + manifest, never a second engine call).

**ADR-020 fix:** the ``TenantContext`` every tenant-scoped tool binds
is now built from the gateway's propagated, authenticated ``Principal``
(``tenant_id``, ``actor_id=principal.subject``,
``actor_roles=principal.role_values()``), not from the caller-supplied
``tenant_id`` argument and a fixed placeholder ``actor_id="mcp-caller"``.
The caller-supplied ``tenant_id`` is still required to match the
principal's own, so a mismatched claim fails loudly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

from cairn_contracts.transformation import SourceFile
from cairn_kernel.errors import NotFoundError, TenantScopeViolationError, ValidationError
from cairn_kernel.security import Principal
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import TransformationPort
from cairn_modules.transformation.runs import TransformationRunRecord, TransformationRunRepository
from cairn_modules.transformation.validation import (
    ValidationPort,
    ValidationRequest,
    run_validation,
)
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

TRANSFORMATION_CONTEXT_ID = "transformation"

TOOL_LIST_SOURCE_FILES = "transformation.list_source_files"
TOOL_GET_RUN = "transformation.get_run"
TOOL_GET_MANIFEST = "transformation.get_manifest"
TOOL_GET_DIFF = "transformation.get_diff"
TOOL_RUN = "transformation.run"
TOOL_VALIDATE = "transformation.validate"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _ProjectArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str


class _RunArgs(_ProjectArgs):
    model_config = ConfigDict(extra="forbid")

    run_id: str


class _RunToolArgs(_ProjectArgs):
    model_config = ConfigDict(extra="forbid")

    created_by: str


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
        correlation_id=f"mcp-transformation-{principal.tenant_id.value}",
    )


def _require_caller_matches_principal(caller_tenant_id: str, principal: Principal) -> None:
    if caller_tenant_id != principal.tenant_id.value:
        raise TenantScopeViolationError(
            f"caller-supplied tenant_id {caller_tenant_id!r} does not match the"
            f" authenticated principal's tenant {principal.tenant_id.value!r}"
        )


def _find_run(
    repository: TransformationRunRepository,
    *,
    tenant_id: str,
    project_id: str,
    run_id: str,
    principal: Principal,
) -> TransformationRunRecord:
    _require_caller_matches_principal(tenant_id, principal)
    with tenant_scope(_scope(principal)):
        for record in repository.list_runs(tenant_id=tenant_id, project_id=project_id):
            if record.run_id == run_id:
                return record
    raise NotFoundError(f"transformation run {run_id} not found")


def build_transformation_server(
    transformation_port: TransformationPort,
    repository: TransformationRunRepository,
    *,
    source_files: Sequence[SourceFile],
    checks: tuple[ValidationPort, ...] = (),
) -> BoundedContextServer:
    """Build the transformation bounded-context's MCP server.
    ``source_files`` is the fixed scope this server reads from -- the
    repository ref CAIRN's own ``RepositorySourcePort`` already fetched
    for this project (``apps/api``'s own composition root resolves
    that); this server does not fetch from Git itself.
    """

    files = tuple(source_files)
    files_by_run: dict[str, tuple[SourceFile, ...]] = {}

    def handle(tool_name: str, arguments: Mapping[str, object], principal: Principal) -> object:
        if tool_name == TOOL_LIST_SOURCE_FILES:
            _parse(_ProjectArgs, arguments)
            return files

        if tool_name == TOOL_GET_RUN:
            args = _parse(_RunArgs, arguments)
            return _find_run(
                repository,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                run_id=args.run_id,
                principal=principal,
            )

        if tool_name == TOOL_GET_MANIFEST:
            args = _parse(_RunArgs, arguments)
            record = _find_run(
                repository,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                run_id=args.run_id,
                principal=principal,
            )
            return record.manifest

        if tool_name == TOOL_GET_DIFF:
            args = _parse(_RunArgs, arguments)
            record = _find_run(
                repository,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                run_id=args.run_id,
                principal=principal,
            )
            run_files = files_by_run.get(args.run_id, files)
            return render_transformation_diff(
                run_id=args.run_id, files=run_files, manifest=record.manifest
            )

        if tool_name == TOOL_RUN:
            args = _parse(_RunToolArgs, arguments)
            _require_caller_matches_principal(args.tenant_id, principal)
            manifest = transformation_port.transform(files)
            with tenant_scope(_scope(principal)):
                record = repository.record_run(
                    tenant_id=args.tenant_id,
                    project_id=args.project_id,
                    manifest=manifest,
                    created_by=args.created_by,
                )
            files_by_run[record.run_id] = files
            return record

        if tool_name == TOOL_VALIDATE:
            args = _parse(_RunArgs, arguments)
            record = _find_run(
                repository,
                tenant_id=args.tenant_id,
                project_id=args.project_id,
                run_id=args.run_id,
                principal=principal,
            )
            run_files = files_by_run.get(args.run_id, files)
            diff = render_transformation_diff(
                run_id=args.run_id, files=run_files, manifest=record.manifest
            )
            request = ValidationRequest(
                run_id=args.run_id, files=run_files, manifest=record.manifest, diff=diff
            )
            return run_validation(request, checks=checks)

        raise ValidationError(f"transformation MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=TRANSFORMATION_CONTEXT_ID,
        name="transformation",
        tools=(
            TOOL_LIST_SOURCE_FILES,
            TOOL_GET_RUN,
            TOOL_GET_MANIFEST,
            TOOL_GET_DIFF,
            TOOL_RUN,
            TOOL_VALIDATE,
        ),
        capabilities={
            TOOL_LIST_SOURCE_FILES: ToolCapability.READ,
            TOOL_GET_RUN: ToolCapability.READ,
            TOOL_GET_MANIFEST: ToolCapability.READ,
            TOOL_GET_DIFF: ToolCapability.READ,
            TOOL_RUN: ToolCapability.PROPOSE,
            TOOL_VALIDATE: ToolCapability.PROPOSE,
        },
        handle=handle,
    )


__all__ = [
    "TOOL_GET_DIFF",
    "TOOL_GET_MANIFEST",
    "TOOL_GET_RUN",
    "TOOL_LIST_SOURCE_FILES",
    "TOOL_RUN",
    "TOOL_VALIDATE",
    "TRANSFORMATION_CONTEXT_ID",
    "build_transformation_server",
]
