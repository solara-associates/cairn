"""R6-08: the ``estate`` bounded context's MCP server (ADR-011, design
§4.1). Four ``READ`` tools over one assessment run's own estate
artifacts -- the workloads and resources R1-06/R1-07 derived, and the
dependency edges between them -- the same shape ``posture_server.py``
already established: a `handle` dispatching by tool name, raising for
an unknown one, calling the module's own application service
(``cairn_modules.assessment.AssessmentService``) and never SQL or a
provider SDK directly.

``cairn_modules.estate`` itself has no persisted repository: a
workload only exists as the output of a specific assessment run
(R1-06/R1-07), read back through the run's own ``AssessmentService``,
the same artifact keys ``cairn_modules.assessment.stages`` writes
(``"workloads"``, ``"resources"``, ``"dependencies"``) -- not a new
estate-specific store.

**ADR-020 fix:** this server previously had no tenant check at all --
every tool resolved an assessment run by ``assessment_run_id`` alone
and returned its artifacts to whoever asked. Every tool now confirms
the fetched run's own ``tenant_id`` matches the gateway's propagated,
authenticated ``Principal`` before returning anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from cairn_kernel.errors import NotFoundError, TenantScopeViolationError, ValidationError
from cairn_kernel.security import Principal
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.assessment import AssessmentRun, AssessmentService
from cairn_modules.estate.workloads import dependencies_of, dependents_of
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)

ESTATE_CONTEXT_ID = "estate"

TOOL_LIST_WORKLOADS = "estate.list_workloads"
TOOL_GET_WORKLOAD = "estate.get_workload"
TOOL_LIST_RESOURCES = "estate.list_resources"
TOOL_GET_DEPENDENCIES = "estate.get_dependencies"


class _RunScopedArgs(BaseModel):
    """Every estate tool is scoped to one assessment run -- an unknown
    key is rejected (A7.input-validation), not silently ignored."""

    model_config = ConfigDict(extra="forbid")

    assessment_run_id: str


class _WorkloadArgs(_RunScopedArgs):
    model_config = ConfigDict(extra="forbid")

    workload_id: str


def _parse(model_cls: type[_ArgsT], arguments: Mapping[str, object]) -> _ArgsT:
    try:
        return model_cls.model_validate(dict(arguments))
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _tenant_scoped_run(
    assessment_service: AssessmentService, *, assessment_run_id: str, principal: Principal
) -> AssessmentRun:
    run = assessment_service.get_run(assessment_run_id)
    if run.tenant_id != principal.tenant_id.value:
        raise TenantScopeViolationError(
            f"run {assessment_run_id} belongs to a different tenant than the caller"
        )
    return run


def build_estate_server(assessment_service: AssessmentService) -> BoundedContextServer:
    """Build the estate bounded-context's MCP server, backed by
    ``assessment_service`` -- the same service ``apps/api``/``apps/worker``
    already use to queue and advance a run."""

    def handle(tool_name: str, arguments: Mapping[str, object], principal: Principal) -> object:
        if tool_name == TOOL_LIST_WORKLOADS:
            args = _parse(_RunScopedArgs, arguments)
            run = _tenant_scoped_run(
                assessment_service, assessment_run_id=args.assessment_run_id, principal=principal
            )
            return run.context.artifacts.get("workloads", ())

        if tool_name == TOOL_GET_WORKLOAD:
            args = _parse(_WorkloadArgs, arguments)
            run = _tenant_scoped_run(
                assessment_service, assessment_run_id=args.assessment_run_id, principal=principal
            )
            for workload in run.context.artifacts.get("workloads", ()):
                if workload.workload_id == args.workload_id:
                    return workload
            raise NotFoundError(
                f"workload {args.workload_id} not found on run {args.assessment_run_id}"
            )

        if tool_name == TOOL_LIST_RESOURCES:
            args = _parse(_RunScopedArgs, arguments)
            run = _tenant_scoped_run(
                assessment_service, assessment_run_id=args.assessment_run_id, principal=principal
            )
            return run.context.artifacts.get("resources", ())

        if tool_name == TOOL_GET_DEPENDENCIES:
            args = _parse(_WorkloadArgs, arguments)
            run = _tenant_scoped_run(
                assessment_service, assessment_run_id=args.assessment_run_id, principal=principal
            )
            dependencies = run.context.artifacts.get("dependencies", ())
            return {
                "depends_on": dependencies_of(args.workload_id, dependencies),
                "depended_on_by": dependents_of(args.workload_id, dependencies),
            }

        raise ValidationError(f"estate MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=ESTATE_CONTEXT_ID,
        name="estate",
        tools=(TOOL_LIST_WORKLOADS, TOOL_GET_WORKLOAD, TOOL_LIST_RESOURCES, TOOL_GET_DEPENDENCIES),
        capabilities={
            TOOL_LIST_WORKLOADS: ToolCapability.READ,
            TOOL_GET_WORKLOAD: ToolCapability.READ,
            TOOL_LIST_RESOURCES: ToolCapability.READ,
            TOOL_GET_DEPENDENCIES: ToolCapability.READ,
        },
        handle=handle,
    )


__all__ = [
    "ESTATE_CONTEXT_ID",
    "TOOL_GET_DEPENDENCIES",
    "TOOL_GET_WORKLOAD",
    "TOOL_LIST_RESOURCES",
    "TOOL_LIST_WORKLOADS",
    "build_estate_server",
]
