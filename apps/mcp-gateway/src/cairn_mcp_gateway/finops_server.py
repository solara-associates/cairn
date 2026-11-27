"""R6-10: the ``finops`` bounded context's MCP server (ADR-011, design
§4.1). Three ``READ`` tools: ``get_baseline``/``get_tco`` read one
assessment run's own already-computed cost artifacts (the same
``cost_baseline``/``tco_result`` keys ``cairn_modules.assessment.
stages`` writes, exactly as ``estate_server.py``/``ingestion_server.py``
already read theirs), and ``list_price_releases`` reads the real price
list registry, seeded once from the real seed
(``pricing/gcp-price-list-seed.yaml``).

Same R-TENANT-01 shape as ``ingestion_server.py``: ``AssessmentService.
get_run`` takes a bare ``run_id`` and does not itself check who is
asking, so ``get_baseline``/``get_tco`` take the caller's own
``tenant_id`` and check it against the run's recorded tenant.
``list_price_releases`` names no run at all -- a price-list release is
CAIRN's own global, versioned artefact (the same reasoning
``mappings_server.py`` already uses for a published mapping release),
so it carries no tenant check.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from cairn_kernel.errors import TenantScopeViolationError, ValidationError
from cairn_kits.mcp import BoundedContextServer, ToolCapability
from cairn_modules.assessment import AssessmentService
from cairn_modules.finops.pricing import InMemoryPriceList
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

#: apps/mcp-gateway/src/cairn_mcp_gateway/finops_server.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PRICE_LIST_SEED = _REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

FINOPS_CONTEXT_ID = "finops"

TOOL_GET_BASELINE = "finops.get_baseline"
TOOL_GET_TCO = "finops.get_tco"
TOOL_LIST_PRICE_RELEASES = "finops.list_price_releases"

_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


class _AssessmentRunArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    assessment_run_id: str


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


def build_finops_server(
    assessment_service: AssessmentService,
    *,
    price_list_seed: Path | str = DEFAULT_PRICE_LIST_SEED,
) -> BoundedContextServer:
    """Build the finops bounded-context's MCP server. ``price_list_seed``
    is loaded once, at construction, into a real ``InMemoryPriceList``
    (the same seed-once shape ``mappings_server.py``/``posture_server.py``
    already use).
    """

    price_list = InMemoryPriceList()
    price_list.load(price_list_seed)

    def handle(tool_name: str, arguments: Mapping[str, object]) -> object:
        if tool_name == TOOL_GET_BASELINE:
            args = _parse(_AssessmentRunArgs, arguments)
            run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return run.context.artifacts.get("cost_baseline")

        if tool_name == TOOL_GET_TCO:
            args = _parse(_AssessmentRunArgs, arguments)
            run = assessment_service.get_run(args.assessment_run_id)
            _require_tenant(run.tenant_id, args.tenant_id, run_id=args.assessment_run_id)
            return run.context.artifacts.get("tco_result")

        if tool_name == TOOL_LIST_PRICE_RELEASES:
            _parse(_NoArgs, arguments)
            return tuple(price_list.get(version) for version in price_list.versions())

        raise ValidationError(f"finops MCP server does not expose tool {tool_name!r}")

    return BoundedContextServer(
        context_id=FINOPS_CONTEXT_ID,
        name="finops",
        tools=(TOOL_GET_BASELINE, TOOL_GET_TCO, TOOL_LIST_PRICE_RELEASES),
        capabilities={
            TOOL_GET_BASELINE: ToolCapability.READ,
            TOOL_GET_TCO: ToolCapability.READ,
            TOOL_LIST_PRICE_RELEASES: ToolCapability.READ,
        },
        handle=handle,
    )


__all__ = [
    "DEFAULT_PRICE_LIST_SEED",
    "FINOPS_CONTEXT_ID",
    "TOOL_GET_BASELINE",
    "TOOL_GET_TCO",
    "TOOL_LIST_PRICE_RELEASES",
    "build_finops_server",
]
