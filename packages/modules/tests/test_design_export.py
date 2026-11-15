"""R2-08: design/plan export bundle and report (spec §16's R2-08 row:
"Machine-readable and human-readable exports").

Covers the acceptance criteria this story sets for itself:

- export round-trip: every field is present on the bundle, and the
  version stamps (``pattern_catalogue_version``/``mapping_release_
  version``/``target_provider``) are consistent -- the exact same field
  names and the exact same values -- across all four sections (design,
  diagram, plan, iac);
- a mismatched input (wrong revision, wrong tenant/project, wrong
  roadmap) is rejected with ``ValidationError``, never silently bundled;
- the human-readable report shows coverage, assumptions and versions,
  all visible, matching the bundle's own data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.diagram_drawio import FakeDiagramRenderer
from cairn_adapters.iac_terraform import FakeIaCGenerator
from cairn_contracts.estate import (
    DecisionStatus,
    Disposition,
    DispositionDecision,
    Equivalence,
    FactStatus,
    Resource,
    Workload,
)
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_contracts.mapping.pattern import Pattern
from cairn_kernel.errors import ValidationError
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design import (
    compile_diagram,
    generate_target_model,
    load_pattern_catalogue,
)
from cairn_modules.planning import generate_iac_plan, generate_roadmap
from cairn_modules.reporting import build_design_export_bundle, render_design_report

REPO_ROOT = Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
OTHER_TENANT = "99999999-9999-9999-9999-999999999999"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"
PLAN_ID = "44444444-4444-4444-4444-444444444444"


def _resource(**overrides: object) -> Resource:
    payload = {
        "resource_id": "res-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "provider": "aws",
        "account_id": "111111111111",
        "region": "eu-west-2",
        "service": "s3",
        "resource_type": "bucket",
        "native_id": "arn:aws:s3:::my-bucket",
        "name": "my-bucket",
        "tags": {},
        "facts": {},
        "provenance": (),
        "status": FactStatus.OBSERVED,
    }
    payload.update(overrides)
    return Resource(**payload)


def _entry(**overrides: object) -> MappingEntry:
    payload = {
        "id": "s3-to-gcs",
        "source_provider": "aws",
        "source_service": "s3",
        "target_provider": "gcp",
        "target_service": "cloud-storage",
        "equivalence": Equivalence.EXACT,
        "caveat": None,
        "regions": (),
        "evidence": "public documentation",
    }
    payload.update(overrides)
    return MappingEntry(**payload)


def _release() -> MappingRelease:
    return MappingRelease(
        version="2026.11.1",
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=(_entry(),),
    )


def _pattern() -> Pattern:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        if pattern.id == "web-app":
            return pattern
    raise AssertionError("web-app seed pattern is missing")


def _design_revision(target_model, *, revision_number: int = 1) -> RevisionRecord:
    return RevisionRecord(
        revision_id=f"design-revision-{revision_number}",
        tenant_id=target_model.tenant_id,
        project_id=target_model.project_id,
        subject_kind="design",
        subject_id=target_model.design_id,
        revision_number=revision_number,
        content_hash=target_model.content_hash,
        input_versions=(("pattern_id", target_model.pattern_id),),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def _plan_revision(roadmap, *, revision_number: int = 1) -> RevisionRecord:
    return RevisionRecord(
        revision_id=f"plan-revision-{revision_number}",
        tenant_id=roadmap.tenant_id,
        project_id=roadmap.project_id,
        subject_kind="plan",
        subject_id=PLAN_ID,
        revision_number=revision_number,
        content_hash=roadmap.content_hash,
        input_versions=(("wave_count", str(len(roadmap.waves))),),
        created_by="alice",
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def _workload(workload_id: str, *, resource_ids: tuple[str, ...]) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name=workload_id,
        environment="UNVERIFIED",
        owner=None,
        business_context=None,
        resource_ids=resource_ids,
        dependency_ids=(),
        facts={},
        disposition=None,
        disposition_confidence=None,
        model_version="r1-07-grouping-v1",
        mapping_version="r1-07-grouping-v1",
    )


def _decision(workload_id: str) -> DispositionDecision:
    return DispositionDecision(
        decision_id=f"decision-{workload_id}",
        tenant_id=TENANT,
        project_id=PROJECT,
        workload_id=workload_id,
        disposition=Disposition.REHOST,
        rationale="lift and shift",
        confidence=0.9,
        status=DecisionStatus.ACCEPTED,
        decided_by="alice",
        decided_at=datetime(2026, 11, 15, tzinfo=UTC),
        model_version="r1-14-classifier-v1",
        mapping_version="r1-14-classifier-v1",
    )


def _build_full_chain():
    """Build one full design -> diagram -> plan -> iac chain for the
    export bundle tests below."""
    estate = (_resource(resource_id="res-1", service="s3"),)
    target_model = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=estate,
        pattern=_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )
    design_revision = _design_revision(target_model)
    diagram = compile_diagram(
        target_model=target_model, revision=design_revision, renderer=FakeDiagramRenderer()
    )
    iac = generate_iac_plan(
        target_model=target_model, revision=design_revision, generator=FakeIaCGenerator()
    )
    workloads = (_workload("wl-1", resource_ids=("res-1",)),)
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=workloads,
        dispositions={"wl-1": _decision("wl-1")},
        target_model=target_model,
    )
    plan_revision = _plan_revision(roadmap)
    return target_model, design_revision, diagram, roadmap, plan_revision, iac


def test_export_bundle_round_trip_every_field_present_and_versions_consistent() -> None:
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    bundle = build_design_export_bundle(
        target_model=target_model,
        design_revision=design_revision,
        diagram=diagram,
        plan_id=PLAN_ID,
        roadmap=roadmap,
        plan_revision=plan_revision,
        iac=iac,
    )

    assert bundle.tenant_id == TENANT
    assert bundle.project_id == PROJECT
    assert bundle.design_id == DESIGN_ID

    assert bundle.design.revision_id == design_revision.revision_id
    assert bundle.design.content_hash == target_model.content_hash
    assert bundle.diagram.artefact_id == diagram.artefact_id
    assert bundle.plan.plan_id == PLAN_ID
    assert bundle.plan.revision_id == plan_revision.revision_id
    assert bundle.iac.artefact_id == iac.artefact_id

    assert bundle.version_stamps_consistent
    for section in (bundle.design, bundle.diagram, bundle.plan, bundle.iac):
        assert section.versions.pattern_catalogue_version == "2026.11.1"
        assert section.versions.mapping_release_version == "2026.11.1"
        assert section.versions.target_provider == "gcp"


def test_export_bundle_field_names_are_identical_across_all_four_sections() -> None:
    """The exact consistency contract 708 (R2-10) will check by name."""
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    bundle = build_design_export_bundle(
        target_model=target_model,
        design_revision=design_revision,
        diagram=diagram,
        plan_id=PLAN_ID,
        roadmap=roadmap,
        plan_revision=plan_revision,
        iac=iac,
    )
    field_names = {
        frozenset(section.versions.__dataclass_fields__)
        for section in (bundle.design, bundle.diagram, bundle.plan, bundle.iac)
    }
    assert field_names == {frozenset({"pattern_catalogue_version", "mapping_release_version", "target_provider"})}


def test_export_bundle_rejects_a_diagram_compiled_from_a_different_revision() -> None:
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    other_revision = _design_revision(target_model, revision_number=2)
    wrong_diagram = replace(diagram, revision_id=other_revision.revision_id)
    with pytest.raises(ValidationError):
        build_design_export_bundle(
            target_model=target_model,
            design_revision=design_revision,
            diagram=wrong_diagram,
            plan_id=PLAN_ID,
            roadmap=roadmap,
            plan_revision=plan_revision,
            iac=iac,
        )


def test_export_bundle_rejects_a_plan_revision_that_does_not_record_this_roadmap() -> None:
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    wrong_plan_revision = replace(plan_revision, content_hash="not-the-real-hash")
    with pytest.raises(ValidationError):
        build_design_export_bundle(
            target_model=target_model,
            design_revision=design_revision,
            diagram=diagram,
            plan_id=PLAN_ID,
            roadmap=roadmap,
            plan_revision=wrong_plan_revision,
            iac=iac,
        )


def test_export_bundle_rejects_a_roadmap_from_a_different_tenant() -> None:
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    wrong_roadmap = replace(roadmap, tenant_id=OTHER_TENANT)
    with pytest.raises(ValidationError):
        build_design_export_bundle(
            target_model=target_model,
            design_revision=design_revision,
            diagram=diagram,
            plan_id=PLAN_ID,
            roadmap=wrong_roadmap,
            plan_revision=plan_revision,
            iac=iac,
        )


def test_export_bundle_rejects_a_design_revision_for_a_different_target_model() -> None:
    target_model, design_revision, diagram, roadmap, plan_revision, iac = _build_full_chain()
    wrong_revision = replace(design_revision, content_hash="not-the-real-hash")
    with pytest.raises(ValidationError):
        build_design_export_bundle(
            target_model=target_model,
            design_revision=wrong_revision,
            diagram=diagram,
            plan_id=PLAN_ID,
            roadmap=roadmap,
            plan_revision=plan_revision,
            iac=iac,
        )


def test_design_report_shows_coverage_assumptions_and_versions() -> None:
    target_model, design_revision, _diagram, roadmap, _plan_revision, iac = _build_full_chain()
    report = render_design_report(
        target_model=target_model,
        design_revision=design_revision,
        plan_id=PLAN_ID,
        roadmap=roadmap,
        iac=iac,
    )

    assert report.tenant_id == TENANT
    assert report.project_id == PROJECT
    assert report.design_id == DESIGN_ID
    assert report.coverage.resource_count == 1
    assert report.coverage.resolved_resource_count == 1
    assert report.coverage.unresolved_resource_count == 0
    assert report.assumptions.pattern_id == target_model.pattern_id
    assert report.versions.pattern_catalogue_version == "2026.11.1"
    assert report.versions.mapping_release_version == "2026.11.1"
    assert report.versions.target_provider == "gcp"
    assert report.plan.plan_id == PLAN_ID
    assert report.plan.wave_count == len(roadmap.waves)
    assert "Design export report" in report.rendered_text
    assert "Pattern catalogue: 2026.11.1" in report.rendered_text
    assert "Mapping release: 2026.11.1" in report.rendered_text


def test_design_report_surfaces_an_unresolved_resource_visibly() -> None:
    estate = (
        _resource(resource_id="res-1", service="s3"),
        _resource(resource_id="res-missing", service="some-legacy-mainframe-service"),
    )
    target_model = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=estate,
        pattern=_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )
    design_revision = _design_revision(target_model)
    iac = generate_iac_plan(
        target_model=target_model, revision=design_revision, generator=FakeIaCGenerator()
    )
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("wl-1", resource_ids=("res-1", "res-missing")),),
        dispositions={"wl-1": _decision("wl-1")},
        target_model=target_model,
    )
    report = render_design_report(
        target_model=target_model,
        design_revision=design_revision,
        plan_id=PLAN_ID,
        roadmap=roadmap,
        iac=iac,
    )
    assert report.coverage.unresolved_resource_count == 1
    assert "res-missing" in report.coverage.unresolved_resource_ids
    assert "res-missing" in report.rendered_text
    assert report.plan.blocked_workload_ids == ("wl-1",)
    assert report.iac.gap_resource_ids == ("res-missing",)
