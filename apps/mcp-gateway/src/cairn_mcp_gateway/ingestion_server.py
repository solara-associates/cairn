"""R6-09: the ``ingestion`` bounded context's MCP server (ADR-011,
design §4.1). Seven ``READ`` tools: three over a file-ingestion run
(``cairn_modules.ingestion.run.CheckpointStore``) and four folding in
what the design originally proposed as a ninth ``assessment`` server
(Allan's decision for this session: implement exactly ADR-011's eight
bounded contexts, no ninth -- see this unit's PR description).

**R-TENANT-01, enforced here rather than assumed.** No component this
server reads from opens a Postgres session (every store behind it is
in-memory -- A5.10's own Postgres adapter is R6-15), so there is no RLS
boundary to lean on the way most of this codebase's tenant isolation
does. ``AssessmentService.get_run``/``CheckpointStore.load`` take only
a bare ``run_id`` and do not themselves check who is asking, so every
tool here takes the caller's own ``tenant_id`` as an explicit argument
and checks it against the run's recorded tenant before returning
anything -- the "app role" enforcement the run sheet's acceptance asks
for, done at this application layer because there is no database role
to do it underneath. **Known limitation, stated rather than hidden:**
``cairn_kits.mcp.BoundedContextServer.handle`` has no parameter for the
authenticated ``Principal`` the gateway already verified
(``McpGateway.call_tool`` authenticates and checks the tool's required
*role* before the handle runs, but never passes the principal's own
*tenant_id* through) -- so this check is only as good as the
``tenant_id`` argument a caller supplies. Closing that gap for every
MCP tool, not just this server's, needs the gateway's own
``ToolHandle`` signature extended to carry the principal through, which
is a larger kits-level change than this unit's own scope; flagged here
for a future unit/ADR rather than quietly worked around.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from cairn_contracts.estate import DispositionDecision
from cairn_kernel.errors import NotFoundError, TenantScopeViolationError, ValidationError
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.assessment import AssessmentRun, AssessmentService
from cairn_modules.ingestion.run import CheckpointStore, IngestionRun, coverage_report
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

INGESTION_CONTEXT_ID = "ingestion"

TOOL_GET_RUN = "ingestion.get_run"
TOOL_LIST_RUNS = "ingestion.list_runs"
TOOL_GET_COVERAGE = "ingestion.get_coverage"
TOOL_ASSESSMENT_GET_RUN = "assessment.get_run"
TOOL_ASSESSMENT_GET_RESULTS = "assessment.get_results"
TOOL_ASSESSMENT_COVERAGE_REPORT = "assessment.coverage_report"
TOOL_ASSESSMENT_GET_DECISION = "assessment.get_decision"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _RunArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    run_id: str


class _ListRunsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str


class _AssessmentRunArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    assessment_run_id: str


class _AssessmentDecisionArgs(_AssessmentRunArgs):
    model_config = ConfigDict(extra="forbid")

    decision_id: str


def _parse(model_cls: type[_ArgsT], arguments: Mapping[str, object]) -> _ArgsT:
    try:
        return model_cls.model_validate(dict(arguments))
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc


def _require_tenant(run_tenant_id: str, caller_tenant_id: str, *, run_id: str) -> None:
    if run_tenant_id != caller_tenant_id:
        raise TenantScopeViolationError(
            f"run {run_id} belongs to a different tenant than the caller"
        )


def _decision(run: AssessmentRun, decision_id: str) -> DispositionDecision:
    decisions: tuple[DispositionDecision, ...] = run.context.artifacts.get(
        "disposition_decisions", ()
    )
    for decision in decisions:
        if decision.decision_id == decision_id:
            return decision
    raise NotFoundError(f"disposition decision {decision_id} not found on run {run.run_id}")


def build_ingestion_server(
    checkpoint_store: CheckpointStore, assessment_service: AssessmentService
) -> BoundedContextServer:
    """Build the ingestion bounded-context's MCP server, backed by the
    file-ingestion ``CheckpointStore`` and the assessment pipeline's own
    ``AssessmentService`` -- two different runs, two different stores,
    one server, because ADR-011's rule is one server per bounded
    context, not one per application service.
    """

    def handle(tool_name: str, arguments: Mapping[str, object]) -> object:
        if tool_name == TOOL_GET_RUN:
            args = _parse(_RunArgs, arguments)
            run: IngestionRun = checkpoint_store.load(args.run_id)
            _require_tenant(run.tenant_id, args.tenant_id, run_id=args.run_id)
            return run

        if tool_name == TOOL_LIST_RUNS:
            args = _parse(_ListRunsArgs, arguments)
            return checkpoint_store.list_runs(tenant_id=args.tenant_id, project_id=args.project_id)

        if tool_name == TOOL_GET_COVERAGE:
            args = _parse(_RunArgs, arguments)
            run = checkpoint_store.load(args.run_id)
            _require_tenant(run.tenant_id, args.tenant_id, run_id=args.run_id)
            return coverage_report(run)

        if tool_name == TOOL_ASSESSMENT_GET_RUN:
            args = _parse(_AssessmentRunArgs, arguments)
            assessment_run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(assessment_run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return assessment_run

        if tool_name == TOOL_ASSESSMENT_GET_RESULTS:
            args = _parse(_AssessmentRunArgs, arguments)
            assessment_run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(assessment_run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return dict(assessment_run.context.artifacts)

        if tool_name == TOOL_ASSESSMENT_COVERAGE_REPORT:
            args = _parse(_AssessmentRunArgs, arguments)
            assessment_run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(assessment_run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return assessment_service.coverage_report(args.assessment_run_id)

        if tool_name == TOOL_ASSESSMENT_GET_DECISION:
            args = _parse(_AssessmentDecisionArgs, arguments)
            assessment_run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(assessment_run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return _decision(assessment_run, args.decision_id)

        raise ValidationError(f"ingestion MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=INGESTION_CONTEXT_ID,
        name="ingestion",
        tools=(
            TOOL_GET_RUN,
            TOOL_LIST_RUNS,
            TOOL_GET_COVERAGE,
            TOOL_ASSESSMENT_GET_RUN,
            TOOL_ASSESSMENT_GET_RESULTS,
            TOOL_ASSESSMENT_COVERAGE_REPORT,
            TOOL_ASSESSMENT_GET_DECISION,
        ),
        capabilities={
            TOOL_GET_RUN: ToolCapability.READ,
            TOOL_LIST_RUNS: ToolCapability.READ,
            TOOL_GET_COVERAGE: ToolCapability.READ,
            TOOL_ASSESSMENT_GET_RUN: ToolCapability.READ,
            TOOL_ASSESSMENT_GET_RESULTS: ToolCapability.READ,
            TOOL_ASSESSMENT_COVERAGE_REPORT: ToolCapability.READ,
            TOOL_ASSESSMENT_GET_DECISION: ToolCapability.READ,
        },
        handle=handle,
    )


__all__ = [
    "INGESTION_CONTEXT_ID",
    "TOOL_ASSESSMENT_COVERAGE_REPORT",
    "TOOL_ASSESSMENT_GET_DECISION",
    "TOOL_ASSESSMENT_GET_RESULTS",
    "TOOL_ASSESSMENT_GET_RUN",
    "TOOL_GET_COVERAGE",
    "TOOL_GET_RUN",
    "TOOL_LIST_RUNS",
    "build_ingestion_server",
]
