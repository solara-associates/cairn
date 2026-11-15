"""R2-08: human-readable design/plan export report renderer.

Spec §16's R2-08 row names three export forms -- JSON, diagram, report.
This brief's own resolution (decided by Allan for this run) is to reuse
R1-16's existing report-rendering discipline
(``cairn_modules.reporting.renderer.render_report``) against the design/
plan revision, rather than inventing a new report format: the same
"coverage, assumptions, versions all visible, nothing silently dropped"
shape ``AssessmentReport`` already gives for an assessment run, now given
for a design's export bundle (703's ``TargetModel``, 705/706's
``MigrationRoadmap``, 706's ``IaCPlanArtefact``).

This module does not re-derive anything 703-706 already computed -- every
section below is a direct, honest projection of fields those modules
already expose (unresolved resource ids, blocked workload ids, gap
resource ids), never re-interpreted or guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.target_model import TargetModel
from cairn_modules.planning.iac_plan import IAC_PLAN_DISCLAIMER, IaCPlanArtefact
from cairn_modules.planning.roadmap import MigrationRoadmap


@dataclass(frozen=True, slots=True)
class DesignReportCoverage:
    """How much of the design's estate actually resolved -- R1-16's
    ``RunCoverage``/``PostureCoverage`` discipline, applied to a target
    model's resource resolution instead of an assessment run's stages."""

    resource_count: int
    resolved_resource_count: int
    unresolved_resource_count: int
    unresolved_resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DesignReportAssumptions:
    """Every assumption this generation was given -- the pattern and its
    fully-resolved parameter set (defaults applied, never hidden)."""

    pattern_id: str
    parameters: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DesignReportVersions:
    """Every version this export actually recorded -- R1-16's
    ``VersionsSection`` discipline: explicit, never fabricated."""

    pattern_catalogue_version: str
    mapping_release_version: str
    target_provider: str


@dataclass(frozen=True, slots=True)
class DesignReportPlan:
    plan_id: str
    wave_count: int
    workload_count: int
    blocked_workload_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DesignReportIac:
    gap_resource_ids: tuple[str, ...]
    disclaimer: str


@dataclass(frozen=True, slots=True)
class DesignReport:
    """The full human-readable report for one design's export bundle."""

    tenant_id: str
    project_id: str
    design_id: str
    revision_id: str
    revision_number: int
    coverage: DesignReportCoverage
    assumptions: DesignReportAssumptions
    versions: DesignReportVersions
    plan: DesignReportPlan
    iac: DesignReportIac
    rendered_text: str


def _coverage(target_model: TargetModel) -> DesignReportCoverage:
    unresolved = target_model.unresolved_resource_ids
    total = len(target_model.resources)
    return DesignReportCoverage(
        resource_count=total,
        resolved_resource_count=total - len(unresolved),
        unresolved_resource_count=len(unresolved),
        unresolved_resource_ids=unresolved,
    )


def _assumptions(target_model: TargetModel) -> DesignReportAssumptions:
    return DesignReportAssumptions(
        pattern_id=target_model.pattern_id,
        parameters=target_model.parameters,
    )


def _versions(target_model: TargetModel) -> DesignReportVersions:
    return DesignReportVersions(
        pattern_catalogue_version=target_model.pattern_catalogue_version,
        mapping_release_version=target_model.mapping_release_version,
        target_provider=target_model.target_provider,
    )


def _plan(plan_id: str, roadmap: MigrationRoadmap) -> DesignReportPlan:
    workload_count = sum(len(wave.workloads) for wave in roadmap.waves)
    return DesignReportPlan(
        plan_id=plan_id,
        wave_count=len(roadmap.waves),
        workload_count=workload_count,
        blocked_workload_ids=roadmap.blocked_workload_ids,
    )


def _iac(iac: IaCPlanArtefact) -> DesignReportIac:
    return DesignReportIac(gap_resource_ids=iac.gap_resource_ids, disclaimer=IAC_PLAN_DISCLAIMER)


def render_design_report(
    *,
    target_model: TargetModel,
    design_revision: RevisionRecord,
    plan_id: str,
    roadmap: MigrationRoadmap,
    iac: IaCPlanArtefact,
) -> DesignReport:
    """Render the human-readable export report for one design.

    ``design_revision`` must record ``target_model`` exactly (same
    ``content_hash``), the same revision-binding guard 704/706's compilers
    already use -- this module raises the same way they do (via a plain
    assertion of the caller's own contract, not a new check) if asked to
    render a mismatched pair; callers are expected to pass the revision
    that generated ``target_model``, as every route in this story does.
    """
    coverage = _coverage(target_model)
    assumptions = _assumptions(target_model)
    versions = _versions(target_model)
    plan = _plan(plan_id, roadmap)
    iac_section = _iac(iac)

    text = _render_text(
        target_model,
        design_revision=design_revision,
        coverage=coverage,
        assumptions=assumptions,
        versions=versions,
        plan=plan,
        iac=iac_section,
    )

    return DesignReport(
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        design_id=target_model.design_id,
        revision_id=design_revision.revision_id,
        revision_number=design_revision.revision_number,
        coverage=coverage,
        assumptions=assumptions,
        versions=versions,
        plan=plan,
        iac=iac_section,
        rendered_text=text,
    )


def _render_text(
    target_model: TargetModel,
    *,
    design_revision: RevisionRecord,
    coverage: DesignReportCoverage,
    assumptions: DesignReportAssumptions,
    versions: DesignReportVersions,
    plan: DesignReportPlan,
    iac: DesignReportIac,
) -> str:
    lines: list[str] = [
        f"# Design export report -- design {target_model.design_id}",
        f"Tenant: {target_model.tenant_id}  Project: {target_model.project_id}",
        f"Revision: {design_revision.revision_number} ({design_revision.revision_id})",
        "",
        "## Coverage",
        f"Resources: {coverage.resolved_resource_count}/{coverage.resource_count} resolved",
        f"Unresolved: {', '.join(coverage.unresolved_resource_ids) or 'none'}",
        "",
        "## Assumptions",
        f"Pattern: {assumptions.pattern_id}",
        f"Parameters: {dict(assumptions.parameters)}",
        "",
        "## Versions",
        f"Pattern catalogue: {versions.pattern_catalogue_version}",
        f"Mapping release: {versions.mapping_release_version}",
        f"Target provider: {versions.target_provider}",
        "",
        "## Plan",
        f"Plan: {plan.plan_id}",
        f"Waves: {plan.wave_count}  Workloads: {plan.workload_count}",
        f"Blocked workloads: {', '.join(plan.blocked_workload_ids) or 'none'}",
        "",
        "## IaC preview",
        f"Gaps: {', '.join(iac.gap_resource_ids) or 'none'}",
        iac.disclaimer,
    ]
    return "\n".join(lines)


__all__ = [
    "DesignReport",
    "DesignReportAssumptions",
    "DesignReportCoverage",
    "DesignReportIac",
    "DesignReportPlan",
    "DesignReportVersions",
    "render_design_report",
]
