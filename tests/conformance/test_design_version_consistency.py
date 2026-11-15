"""R2-10: version-consistency conformance check (spec §16's R2-10 row:
"Diagram, plan and IaC share model/mapping/pattern versions"; spec
§15.2's release gate 8: "Every generated diagram/plan records registry
and pattern versions and exposes unresolved mappings").

This is the mechanical enforcement of gate 8, the same relationship
R0-19's classification matrix has to gate 2. It does not depend on 707's
export bundle (``cairn_modules.reporting.design_export``) -- it checks
703-706's artefacts directly: 704's compiled diagram, 705's roadmap/plan
revision and 706's IaC plan preview, all generated from one 703
``TargetModel``.

The version-stamp field names it checks by
(``pattern_catalogue_version``/``mapping_release_version``/
``target_provider``) are the exact three names 707's
``cairn_modules.reporting.design_export.VersionStamp`` already uses --
reused here rather than inventing a second spelling, per this story's own
brief.

Two things a merged pipeline must never silently get wrong, grounded in
code already merged by 703-706:

1. Version/identity consistency. 704's ``DiagramArtefact`` and 706's
   ``IaCPlanArtefact`` are *validated* at construction time to have been
   built from the exact ``design_revision``/``target_model`` given to
   them (``build_diagram_model``/``build_iac_plan_model`` both raise
   ``ValidationError`` on a content-hash mismatch) -- so a diagram or IaC
   preview compiled from the wrong target model never gets this far.
   705's ``generate_roadmap``, by contrast, performs **no such
   validation**: it accepts whatever ``TargetModel`` it is given with no
   check against the design revision the diagram/IaC preview were
   compiled from. That gap -- a roadmap silently generated against a
   different mapping release or pattern catalogue version than the
   diagram/IaC preview it is meant to accompany -- is exactly what this
   rule exists to catch; nothing in 703-706 catches it today.
2. Unresolved-mapping visibility (gate 8's "exposes unresolved
   mappings" half). Any ``TargetResourceEntry`` the resolver could not
   resolve, or resolved to a mapping that isn't actually usable, must be
   visible in both the diagram (a non-``EXACT`` marker; 704's
   distinct-marker rule) and the IaC preview (a named ``GAP``; 706's
   named-gap rule).
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
from cairn_kernel.hex import TenantId
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.design import (
    FakeDesignRevisionRepository,
    compile_diagram,
    generate_target_model,
    load_pattern_catalogue,
)
from cairn_modules.design.diagram import DiagramArtefact, DiagramShapeMarker
from cairn_modules.design.target_model import TargetModel, TargetResourceStatus
from cairn_modules.planning import FakePlanRevisionRepository, generate_iac_plan, generate_roadmap
from cairn_modules.planning.iac_plan import IaCPlanArtefact, IaCResourceStatus

REPO_ROOT = Path(__file__).parents[2]
PATTERNS_DIR = REPO_ROOT / "patterns"

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"
PLAN_ID = "44444444-4444-4444-4444-444444444444"


# --- fixtures, following the style 703-706's own test suites already use --


def _context(tenant: str = TENANT) -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=None,
        actor_id="alice",
        actor_roles=(),
        correlation_id="corr-1",
    )


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


def _release(*entries: MappingEntry, version: str = "2026.11.1") -> MappingRelease:
    return MappingRelease(
        version=version,
        released_at=datetime(2026, 11, 9, tzinfo=UTC),
        status=ReleaseStatus.DRAFT,
        entries=entries or (_entry(),),
    )


def _pattern() -> Pattern:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        if pattern.id == "web-app":
            return pattern
    raise AssertionError("web-app seed pattern is missing")


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


def _target_model(
    *,
    estate: tuple[Resource, ...],
    mapping_release: MappingRelease,
    pattern_catalogue_version: str = "2026.11.1",
    target_provider: str = "gcp",
) -> TargetModel:
    return generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=estate,
        pattern=_pattern(),
        pattern_catalogue_version=pattern_catalogue_version,
        mapping_release=mapping_release,
        target_provider=target_provider,
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )


def _version_triple(target_model: TargetModel) -> tuple[str, str, str]:
    return (
        target_model.pattern_catalogue_version,
        target_model.mapping_release_version,
        target_model.target_provider,
    )


def _build_chain(target_model: TargetModel, *, roadmap_target_model: TargetModel | None = None):
    """Build one design -> diagram/roadmap(plan)/IaC chain, each
    generated the way 704/705/706's own real code generates them.

    ``roadmap_target_model`` lets a test deliberately generate the
    roadmap/plan from a *different* ``TargetModel`` than the one the
    diagram and IaC preview were compiled from -- exactly the scenario
    R-VER-01 exists to catch, since 705's ``generate_roadmap`` performs
    no validation against the design revision at all (unlike 704/706).
    """
    with tenant_scope(_context()):
        design_revision = FakeDesignRevisionRepository().create_revision(
            design_id=DESIGN_ID, target_model=target_model, created_by="alice"
        )
        diagram = compile_diagram(
            target_model=target_model, revision=design_revision, renderer=FakeDiagramRenderer()
        )
        iac = generate_iac_plan(
            target_model=target_model, revision=design_revision, generator=FakeIaCGenerator()
        )

        plan_target_model = roadmap_target_model or target_model
        workloads = (_workload("wl-1", resource_ids=tuple(e.resource_id for e in target_model.resources)),)
        roadmap = generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            workloads=workloads,
            dispositions={"wl-1": _decision("wl-1")},
            target_model=plan_target_model,
        )
        plan_revision = FakePlanRevisionRepository().create_revision(
            plan_id=PLAN_ID, roadmap=roadmap, created_by="alice"
        )

    return design_revision, diagram, roadmap, plan_revision, iac, plan_target_model


# --- the check itself ----------------------------------------------------


def assert_design_artefacts_share_versions(
    *,
    target_model: TargetModel,
    design_revision,
    diagram: DiagramArtefact,
    roadmap_target_model: TargetModel,
    iac: IaCPlanArtefact,
) -> None:
    """R2-10's own check: the mapping release version, pattern catalogue
    version and target-model revision hash recorded by the diagram
    (704), the roadmap/plan (705) and the IaC preview (706) must be
    identical -- not just present, actually equal.

    - The diagram and the IaC preview are bound, at construction time,
      to the exact ``design_revision`` passed to them (``revision_id``
      match) -- that binding itself is checked here, not assumed.
    - The design revision's own ``input_versions`` (``cairn_modules.
      design.revisions._input_versions``) is the one place the design's
      ``pattern_catalogue_version``/``mapping_release_version``/
      ``target_provider`` triple is recorded for the design/diagram side
      -- read by field name, the same three names 707's ``VersionStamp``
      uses.
    - The IaC preview carries the same triple natively on its own
      ``IaCPlanModel`` (``pattern_catalogue_version``/
      ``mapping_release_version``/``target_provider``).
    - The roadmap/plan carries none of these fields natively (705's
      ``MigrationRoadmap`` only records wave/workload counts) -- the
      only honest way to check what it was generated against is the
      ``TargetModel`` actually given to ``generate_roadmap`` for this
      plan, ``roadmap_target_model``.
    """
    assert diagram.revision_id == design_revision.revision_id, (
        "diagram was not compiled from the given design revision"
    )
    assert iac.revision_id == design_revision.revision_id, (
        "IaC preview was not generated from the given design revision"
    )

    design_input_versions = dict(design_revision.input_versions)
    diagram_triple = (
        design_input_versions["pattern_catalogue_version"],
        design_input_versions["mapping_release_version"],
        design_input_versions["target_provider"],
    )
    iac_triple = (
        iac.model.pattern_catalogue_version,
        iac.model.mapping_release_version,
        iac.model.target_provider,
    )
    design_triple = _version_triple(target_model)
    plan_triple = _version_triple(roadmap_target_model)

    triples = {
        "design": design_triple,
        "diagram": diagram_triple,
        "plan": plan_triple,
        "iac": iac_triple,
    }
    distinct = set(triples.values())
    assert len(distinct) == 1, (
        f"pattern_catalogue_version/mapping_release_version/target_provider diverge "
        f"across design/diagram/plan/iac: {triples}"
    )

    hashes = {
        "design": target_model.content_hash,
        "diagram": diagram.model.content_hash,
        "plan": roadmap_target_model.content_hash,
        "iac": iac.model.target_model_content_hash,
    }
    distinct_hashes = set(hashes.values())
    assert len(distinct_hashes) == 1, (
        f"target-model content hash diverges across design/diagram/plan/iac: {hashes}"
    )


# --- tests -----------------------------------------------------------------


def test_diagram_plan_and_iac_share_identical_versions_and_target_model_hash() -> None:
    target_model = _target_model(estate=(_resource(resource_id="res-1", service="s3"),), mapping_release=_release())
    design_revision, diagram, roadmap, plan_revision, iac, plan_target_model = _build_chain(target_model)

    assert roadmap.plan_id == PLAN_ID
    assert plan_revision.content_hash == roadmap.content_hash

    assert_design_artefacts_share_versions(
        target_model=target_model,
        design_revision=design_revision,
        diagram=diagram,
        roadmap_target_model=plan_target_model,
        iac=iac,
    )


def test_mismatched_mapping_release_version_across_artefacts_fails_the_check() -> None:
    """Negative test: the roadmap/plan is deliberately generated from a
    target model recorded against a *different* mapping release version
    than the one the diagram and IaC preview were compiled from. Proves
    the check actually discriminates -- it is not a vacuous pass."""
    estate = (_resource(resource_id="res-1", service="s3"),)
    target_model = _target_model(estate=estate, mapping_release=_release(version="2026.11.1"))
    mismatched_target_model = _target_model(estate=estate, mapping_release=_release(version="2026.12.1"))

    design_revision, diagram, _roadmap, _plan_revision, iac, plan_target_model = _build_chain(
        target_model, roadmap_target_model=mismatched_target_model
    )

    with pytest.raises(AssertionError, match="diverge"):
        assert_design_artefacts_share_versions(
            target_model=target_model,
            design_revision=design_revision,
            diagram=diagram,
            roadmap_target_model=plan_target_model,
            iac=iac,
        )


def test_mismatched_pattern_catalogue_version_across_artefacts_fails_the_check() -> None:
    """A second, independent field mismatch (pattern catalogue version
    rather than mapping release version) must be caught too -- the check
    is not accidentally keyed on only one of the three fields."""
    estate = (_resource(resource_id="res-1", service="s3"),)
    release = _release()
    target_model = _target_model(estate=estate, mapping_release=release, pattern_catalogue_version="2026.11.1")
    mismatched_target_model = _target_model(estate=estate, mapping_release=release, pattern_catalogue_version="2025.01.1")

    design_revision, diagram, _roadmap, _plan_revision, iac, plan_target_model = _build_chain(
        target_model, roadmap_target_model=mismatched_target_model
    )

    with pytest.raises(AssertionError, match="diverge"):
        assert_design_artefacts_share_versions(
            target_model=target_model,
            design_revision=design_revision,
            diagram=diagram,
            roadmap_target_model=plan_target_model,
            iac=iac,
        )


def test_diagram_not_compiled_from_the_given_revision_fails_the_check() -> None:
    """A diagram artefact that claims a revision_id it was not actually
    compiled from must be rejected, never silently treated as matching."""
    target_model = _target_model(estate=(_resource(resource_id="res-1", service="s3"),), mapping_release=_release())
    design_revision, diagram, _roadmap, _plan_revision, iac, plan_target_model = _build_chain(target_model)
    wrong_diagram = replace(diagram, revision_id="not-the-real-revision-id")

    with pytest.raises(AssertionError, match="was not compiled"):
        assert_design_artefacts_share_versions(
            target_model=target_model,
            design_revision=design_revision,
            diagram=wrong_diagram,
            roadmap_target_model=plan_target_model,
            iac=iac,
        )


# --- gate 8's other half: unresolved mappings exposed in diagram + IaC -----


def test_unresolved_mapping_is_visible_in_both_the_diagram_and_the_iac_preview() -> None:
    """Gate 8's "exposes unresolved mappings" half: a resource the
    resolver could not resolve at all (no catalogue entry for this
    service pair) must be visible as a distinct, non-EXACT marker in the
    diagram (704) and as a named GAP in the IaC preview (706) -- never
    silently dropped from either."""
    estate = (
        _resource(resource_id="res-ok", service="s3"),
        _resource(resource_id="res-missing", service="some-legacy-mainframe-service"),
    )
    target_model = _target_model(estate=estate, mapping_release=_release())
    assert "res-missing" in target_model.unresolved_resource_ids
    unresolved_entry = next(e for e in target_model.resources if e.resource_id == "res-missing")
    assert unresolved_entry.status is TargetResourceStatus.UNRESOLVED

    _design_revision, diagram, _roadmap, _plan_revision, iac, _plan_target_model = _build_chain(target_model)

    diagram_shape = next(shape for shape in diagram.model.shapes if shape.shape_id == "res-missing")
    assert diagram_shape.marker is DiagramShapeMarker.UNRESOLVED
    assert diagram_shape.marker is not DiagramShapeMarker.EXACT
    assert "res-missing" in diagram.unresolved_shape_ids

    iac_resource = next(r for r in iac.model.resources if r.resource_id == "res-missing")
    assert iac_resource.status is IaCResourceStatus.GAP
    assert "res-missing" in iac.gap_resource_ids


def test_unavailable_catalogue_entry_is_visible_in_both_the_diagram_and_the_iac_preview() -> None:
    """The second UNRESOLVED/UNAVAILABLE shape: a catalogue entry exists
    but its own equivalence is UNAVAILABLE -- the resolver raises
    (never invents a substitute), and this still ends up a distinct
    marker in the diagram and a named gap in the IaC preview."""
    estate = (
        _resource(resource_id="res-ok", service="s3"),
        _resource(resource_id="res-dns", service="route53"),
    )
    release = _release(
        _entry(),
        _entry(
            id="route53-unavailable",
            source_service="route53",
            target_service=None,
            equivalence=Equivalence.UNAVAILABLE,
            caveat="DNS is out of scope for this migration pattern",
        ),
    )
    target_model = _target_model(estate=estate, mapping_release=release)
    assert "res-dns" in target_model.unresolved_resource_ids

    _design_revision, diagram, _roadmap, _plan_revision, iac, _plan_target_model = _build_chain(target_model)

    diagram_shape = next(shape for shape in diagram.model.shapes if shape.shape_id == "res-dns")
    assert diagram_shape.marker is not DiagramShapeMarker.EXACT

    iac_resource = next(r for r in iac.model.resources if r.resource_id == "res-dns")
    assert iac_resource.status is IaCResourceStatus.GAP
    assert "res-dns" in iac.gap_resource_ids
