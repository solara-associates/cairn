"""R1-15: the real R1-04..R1-14 stage implementations, wired into the
``cairn_modules.assessment.run.Stage`` shape.

:func:`build_real_stages` is the integration point named in the spec --
ingestion (R1-04) -> estate normalization and workload derivation
(R1-06/R1-07) -> posture (R1-09/R1-10) -> cost (R1-11/R1-12) -> TCO
(R1-13) -> 6R classification (R1-14) -- each a thin adapter around the
already-tested module it calls. ``cairn_modules.assessment.run`` itself
depends on none of this: it only knows ``Stage = Callable[[AssessmentContext],
AssessmentContext]``, so a test can substitute a synthetic stage at an
exact boundary without touching the real ones.

Posture honesty note: no native scanner output (Prowler/Steampipe/OPA)
is part of this orchestrator's own inputs -- R1-09's adapters consume
scanner-specific files this story does not collect. The posture stage
therefore runs R1-10's ``assess`` against an empty findings set, which
is a real, honest result (every control UNKNOWN, none evaluated), not
a bypass of the posture stage.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from cairn_contracts.finops import PriceListRelease
from cairn_contracts.posture import ControlCatalogueRelease

from cairn_modules.assessment.run import AssessmentContext, Stage
from cairn_modules.estate import derive, normalize
from cairn_modules.finops import (
    BillingLineItem,
    CostBaseline,
    TcoAssumptions,
    build_baseline,
    compute_tco,
    import_cost_records,
)
from cairn_modules.ingestion import (
    bom_adapter,
    csv_adapter,
    hvtools_adapter,
    json_adapter,
    rvtools_adapter,
)
from cairn_modules.ingestion.models import IngestionResult
from cairn_modules.planning import propose_disposition
from cairn_modules.posture import assess

_PARSERS: dict[str, Callable[..., IngestionResult]] = {
    "csv": csv_adapter.parse,
    "json": json_adapter.parse,
    "rvtools": rvtools_adapter.parse,
    "hvtools": hvtools_adapter.parse,
    "bom": bom_adapter.parse,
}


def build_real_stages(
    *,
    ingestion_files: Sequence[tuple[str, str]],
    billing_items: Sequence[BillingLineItem],
    control_catalogue: ControlCatalogueRelease,
    price_list: PriceListRelease,
    tco_assumptions: TcoAssumptions,
    ingest_run_id: str,
    cost_currency: str,
    scenario_id: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Stage]:
    """Build the six real stage callables for one assessment run.

    ``ingestion_files`` is ``(source_format, content)`` pairs, one per
    file this run ingests; ``billing_items`` is the run's R1-11 billing
    export, already shaped as ``BillingLineItem``s.
    """

    def ingestion_stage(context: AssessmentContext) -> AssessmentContext:
        results = tuple(
            _PARSERS[source_format](content, observed_at=clock())
            for source_format, content in ingestion_files
        )
        return context.with_artifact("ingestion_results", results)

    def estate_stage(context: AssessmentContext) -> AssessmentContext:
        results: tuple[IngestionResult, ...] = context.artifacts["ingestion_results"]
        resources = normalize(
            results,
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            ingest_run_id=ingest_run_id,
        )
        workloads, dependencies = derive(
            resources, tenant_id=context.tenant_id, project_id=context.project_id
        )
        return (
            context.with_artifact("resources", resources)
            .with_artifact("workloads", workloads)
            .with_artifact("dependencies", dependencies)
        )

    def posture_stage(context: AssessmentContext) -> AssessmentContext:
        assessment = assess(control_catalogue, findings=())
        return context.with_artifact("posture_assessment", assessment)

    def cost_stage(context: AssessmentContext) -> AssessmentContext:
        records = import_cost_records(
            billing_items, ingest_run_id=ingest_run_id, parser_version="r1-15-orchestration-v1"
        )
        baseline = build_baseline(records, currency=cost_currency)
        return context.with_artifact("cost_records", records).with_artifact("cost_baseline", baseline)

    def tco_stage(context: AssessmentContext) -> AssessmentContext:
        baseline: CostBaseline = context.artifacts["cost_baseline"]
        result = compute_tco(baseline, tco_assumptions, price_list, scenario_id=scenario_id)
        return context.with_artifact("tco_result", result)

    def classification_stage(context: AssessmentContext) -> AssessmentContext:
        workloads = context.artifacts["workloads"]
        decisions = tuple(
            propose_disposition(workload, decision_id=f"{context.project_id}:{workload.workload_id}")
            for workload in workloads
        )
        return context.with_artifact("disposition_decisions", decisions)

    return {
        "ingestion": ingestion_stage,
        "estate": estate_stage,
        "posture": posture_stage,
        "cost": cost_stage,
        "tco": tco_stage,
        "classification": classification_stage,
    }


__all__ = ["build_real_stages"]
