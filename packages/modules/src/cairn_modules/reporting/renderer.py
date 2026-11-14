"""R1-16: human-readable assessment report renderer.

Renders a completed (or incomplete) R1-15 ``AssessmentRun`` into a
report that shows coverage, explicit assumptions and every version
recorded -- never silently omitting a gap. An incomplete run (stopped
at a failed stage, or simply not yet finished) renders every section it
can from what the run's context actually has, and explicit ``None``/
empty values everywhere else -- the coverage gap is visible in the
rendered text, not hidden by a crash or a dropped section.

ADR-008: the report must reference the evidence package hash. No
evidence package exists yet at this story (R1-17 builds one); this
module carries an explicit, named placeholder field
(``AssessmentReport.evidence_package_hash``, always ``None`` here) for
R1-17 to fill in, rather than inventing a reference scheme now.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn_modules.assessment import AssessmentRun, coverage_report


@dataclass(frozen=True, slots=True)
class RunCoverage:
    """The run's own stage coverage (reused from R1-15's coverage_report)."""

    state: str
    coverage: float
    completed_stages: tuple[str, ...]
    pending_stages: tuple[str, ...]
    failures: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class PostureCoverage:
    """R1-10's own coverage output, reused as-is -- or absent if the
    posture stage never ran.
    """

    release_version: str | None
    evaluated_control_ids: tuple[str, ...]
    not_evaluated_control_ids: tuple[str, ...]
    total_controls: int


@dataclass(frozen=True, slots=True)
class CostCoverage:
    """R1-12's own attributable/unallocated split, reused as-is -- or
    absent if the cost stage never ran.
    """

    currency: str | None
    total_amount_minor: int | None
    attributable_amount_minor: int | None
    unallocated_amount_minor: int | None
    missing_tag_cost_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TcoAssumptionsSection:
    """R1-13's TCO assumptions, stated explicitly -- or absent if the
    TCO stage never ran.
    """

    horizon_periods: int | None
    growth_rate: float | None
    discount_rate: float | None


@dataclass(frozen=True, slots=True)
class VersionsSection:
    """Every version this run actually recorded.

    ``mapping_release_version`` is always ``None`` today: R1-15's
    pipeline does not use R0-14's mapping registry (its six stages are
    ingestion/estate/posture/cost/tco/classification only), so there is
    nothing to report there honestly -- never fabricated to fill the
    field the acceptance text names.
    """

    control_catalogue_version: str | None
    price_list_version: str | None
    mapping_release_version: str | None
    parser_versions: tuple[str, ...]
    workload_derivation_version: str | None
    classification_version: str | None


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    """The full human-readable report for one R1-15 run."""

    run_id: str
    tenant_id: str
    project_id: str
    run_coverage: RunCoverage
    posture_coverage: PostureCoverage
    cost_coverage: CostCoverage
    tco_assumptions: TcoAssumptionsSection
    versions: VersionsSection
    #: ADR-008 placeholder -- R1-17 wires the real evidence package hash
    #: in here. Never anything but ``None`` until then.
    evidence_package_hash: str | None
    rendered_text: str


def _run_coverage(run: AssessmentRun) -> RunCoverage:
    report = coverage_report(run)
    return RunCoverage(
        state=report["state"],
        coverage=report["coverage"],
        completed_stages=tuple(report["completed_stages"]),
        pending_stages=tuple(report["pending_stages"]),
        failures=tuple(report["failures"]),
    )


def _posture_coverage(run: AssessmentRun) -> PostureCoverage:
    assessment = run.context.artifacts.get("posture_assessment")
    if assessment is None:
        return PostureCoverage(
            release_version=None, evaluated_control_ids=(), not_evaluated_control_ids=(), total_controls=0
        )
    coverage = assessment.coverage
    return PostureCoverage(
        release_version=assessment.release_version,
        evaluated_control_ids=coverage.evaluated_control_ids,
        not_evaluated_control_ids=coverage.not_evaluated_control_ids,
        total_controls=coverage.total_controls,
    )


def _cost_coverage(run: AssessmentRun) -> CostCoverage:
    baseline = run.context.artifacts.get("cost_baseline")
    if baseline is None:
        return CostCoverage(
            currency=None,
            total_amount_minor=None,
            attributable_amount_minor=None,
            unallocated_amount_minor=None,
            missing_tag_cost_ids=(),
        )
    return CostCoverage(
        currency=baseline.currency,
        total_amount_minor=baseline.total_amount_minor,
        attributable_amount_minor=baseline.attributable_amount_minor,
        unallocated_amount_minor=baseline.unallocated_amount_minor,
        missing_tag_cost_ids=baseline.missing_tag_cost_ids,
    )


def _tco_assumptions(run: AssessmentRun) -> TcoAssumptionsSection:
    result = run.context.artifacts.get("tco_result")
    if result is None:
        return TcoAssumptionsSection(horizon_periods=None, growth_rate=None, discount_rate=None)
    assumptions = result.assumptions
    return TcoAssumptionsSection(
        horizon_periods=assumptions.horizon_periods,
        growth_rate=assumptions.growth_rate,
        discount_rate=assumptions.discount_rate,
    )


def _versions(run: AssessmentRun) -> VersionsSection:
    posture = run.context.artifacts.get("posture_assessment")
    tco_result = run.context.artifacts.get("tco_result")
    workloads = run.context.artifacts.get("workloads")
    decisions = run.context.artifacts.get("disposition_decisions")
    ingestion_results = run.context.artifacts.get("ingestion_results")

    parser_versions = (
        tuple(sorted({result.parser_version for result in ingestion_results}))
        if ingestion_results
        else ()
    )

    return VersionsSection(
        control_catalogue_version=posture.release_version if posture is not None else None,
        price_list_version=tco_result.price_list_version if tco_result is not None else None,
        mapping_release_version=None,
        parser_versions=parser_versions,
        workload_derivation_version=workloads[0].model_version if workloads else None,
        classification_version=decisions[0].model_version if decisions else None,
    )


def render_report(run: AssessmentRun) -> AssessmentReport:
    """Render ``run`` -- completed or not -- into a human-readable report.

    Every section renders what the run's context actually has; a
    section whose stage never ran (or failed before producing output)
    renders explicit ``None``/empty values, visible in ``rendered_text``,
    rather than being silently dropped or raising.
    """
    run_coverage = _run_coverage(run)
    posture_coverage = _posture_coverage(run)
    cost_coverage = _cost_coverage(run)
    tco_assumptions = _tco_assumptions(run)
    versions = _versions(run)

    text = _render_text(
        run,
        run_coverage=run_coverage,
        posture_coverage=posture_coverage,
        cost_coverage=cost_coverage,
        tco_assumptions=tco_assumptions,
        versions=versions,
    )

    return AssessmentReport(
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_coverage=run_coverage,
        posture_coverage=posture_coverage,
        cost_coverage=cost_coverage,
        tco_assumptions=tco_assumptions,
        versions=versions,
        evidence_package_hash=None,
        rendered_text=text,
    )


def _stages_completed_line(run_coverage: RunCoverage) -> str:
    total = len(run_coverage.completed_stages) + len(run_coverage.pending_stages)
    return f"Stages completed: {run_coverage.coverage:.0%} ({len(run_coverage.completed_stages)}/{total})"


def _render_text(
    run: AssessmentRun,
    *,
    run_coverage: RunCoverage,
    posture_coverage: PostureCoverage,
    cost_coverage: CostCoverage,
    tco_assumptions: TcoAssumptionsSection,
    versions: VersionsSection,
) -> str:
    lines: list[str] = [
        f"# Assessment report -- run {run.run_id}",
        f"Tenant: {run.tenant_id}  Project: {run.project_id}",
        "",
        "## Run coverage",
        f"State: {run_coverage.state}",
        _stages_completed_line(run_coverage),
        f"Pending stages: {', '.join(run_coverage.pending_stages) or 'none'}",
        f"Failures: {run_coverage.failures or 'none'}",
        "",
        "## Posture coverage",
        f"Control catalogue version: {posture_coverage.release_version or 'UNVERIFIED -- stage did not run'}",
        f"Controls evaluated: {len(posture_coverage.evaluated_control_ids)}/{posture_coverage.total_controls}",
        f"Not evaluated: {', '.join(posture_coverage.not_evaluated_control_ids) or 'none'}",
        "",
        "## Cost coverage",
        f"Currency: {cost_coverage.currency or 'UNVERIFIED -- stage did not run'}",
        f"Total: {cost_coverage.total_amount_minor if cost_coverage.total_amount_minor is not None else 'UNVERIFIED'}",
        f"Attributable: {cost_coverage.attributable_amount_minor if cost_coverage.attributable_amount_minor is not None else 'UNVERIFIED'}",
        f"Unallocated: {cost_coverage.unallocated_amount_minor if cost_coverage.unallocated_amount_minor is not None else 'UNVERIFIED'}",
        f"Missing-tag records: {', '.join(cost_coverage.missing_tag_cost_ids) or 'none'}",
        "",
        "## TCO assumptions",
        f"Horizon periods: {tco_assumptions.horizon_periods if tco_assumptions.horizon_periods is not None else 'UNVERIFIED -- stage did not run'}",
        f"Growth rate: {tco_assumptions.growth_rate if tco_assumptions.growth_rate is not None else 'UNVERIFIED'}",
        f"Discount rate: {tco_assumptions.discount_rate if tco_assumptions.discount_rate is not None else 'UNVERIFIED'}",
        "",
        "## Versions",
        f"Control catalogue: {versions.control_catalogue_version or 'UNVERIFIED'}",
        f"Price list: {versions.price_list_version or 'UNVERIFIED'}",
        f"Mapping release: {versions.mapping_release_version or 'not recorded -- this pipeline does not use the mapping registry'}",
        f"Ingestion parser versions: {', '.join(versions.parser_versions) or 'UNVERIFIED'}",
        f"Workload derivation: {versions.workload_derivation_version or 'UNVERIFIED'}",
        f"6R classification: {versions.classification_version or 'UNVERIFIED'}",
        "",
        "## Evidence",
        "Evidence package hash: PENDING -- R1-17 fills this in",
    ]
    return "\n".join(lines)


__all__ = [
    "AssessmentReport",
    "CostCoverage",
    "PostureCoverage",
    "RunCoverage",
    "TcoAssumptionsSection",
    "VersionsSection",
    "render_report",
]
