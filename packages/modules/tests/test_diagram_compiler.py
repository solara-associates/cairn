"""R2-05: the diagram compiler (spec §16's R2-05 row: "Approximate/
unavailable/unresolved distinct; no invented shapes").

Tests assert on the structured pre-render ``DiagramModel`` the compiler
produces -- never on the real Draw.io emitter's exact XML bytes, which
is brittle (the same pattern this codebase already uses for other
renderers, e.g. ``test_reporting_renderer.py``). The fake/deterministic
adapter (``cairn_adapters.diagram_drawio.FakeDiagramRenderer``) stands
in for the port in every test here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.diagram_drawio import DrawioXmlDiagramRenderer, FakeDiagramRenderer
from cairn_contracts.estate import Equivalence, FactStatus, Resource
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_contracts.mapping.pattern import Pattern, PatternParameterType
from cairn_kernel.errors import ValidationError
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design import (
    DiagramShapeMarker,
    build_diagram_model,
    compile_diagram,
    generate_target_model,
    load_pattern_catalogue,
)

REPO_ROOT = Path(__file__).parents[3]
PATTERNS_DIR = REPO_ROOT / "patterns"

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
DESIGN_ID = "33333333-3333-3333-3333-333333333333"


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


def _web_app_pattern() -> Pattern:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        if pattern.id == "web-app":
            return pattern
    raise AssertionError("web-app seed pattern is missing")


def _revision_for(target_model: object, *, revision_number: int = 1) -> RevisionRecord:
    return RevisionRecord(
        revision_id=f"revision-{revision_number}",
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


def _mixed_estate() -> tuple[Resource, ...]:
    return (
        # EXACT: resolves, supported in-region, EXACT equivalence.
        _resource(resource_id="res-exact", service="s3"),
        # APPROXIMATE: resolves, supported in-region, APPROXIMATE equivalence.
        _resource(resource_id="res-approx", service="rds"),
        # UNAVAILABLE: resolves (an entry exists), but not supported in
        # this resource's region.
        _resource(resource_id="res-region", service="dynamodb", region="ap-southeast-2"),
        # UNAVAILABLE: resolves, but the catalogue marks it UNSUPPORTED.
        _resource(resource_id="res-unsupported", service="sagemaker"),
        # UNRESOLVED: no catalogue entry exists for this pair at all.
        _resource(resource_id="res-missing", service="some-legacy-mainframe-service"),
        # UNRESOLVED: a catalogue entry exists but its own equivalence
        # is UNAVAILABLE -- the resolver raises, never a substitute.
        _resource(resource_id="res-entry-unavailable", service="route53"),
    )


def _mixed_release() -> MappingRelease:
    return _release(
        _entry(id="s3", source_service="s3", target_service="cloud-storage", equivalence=Equivalence.EXACT),
        _entry(
            id="rds",
            source_service="rds",
            target_service="cloud-sql",
            equivalence=Equivalence.APPROXIMATE,
            caveat="managed-instance sizing differs",
        ),
        _entry(
            id="dynamodb",
            source_service="dynamodb",
            target_service="firestore",
            equivalence=Equivalence.EXACT,
            regions=("eu-west-2",),
        ),
        _entry(
            id="sagemaker",
            source_service="sagemaker",
            target_service=None,
            equivalence=Equivalence.UNSUPPORTED,
            caveat="no managed ML platform offered in this pattern",
        ),
        _entry(
            id="route53",
            source_service="route53",
            target_service=None,
            equivalence=Equivalence.UNAVAILABLE,
            caveat="DNS is out of scope for this migration pattern",
        ),
    )


def _mixed_target_model():
    return generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=_web_app_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters={"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )


# --- marker rule -----------------------------------------------------------


def test_marker_rule_distinguishes_all_four_states() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    diagram = build_diagram_model(target_model=model, revision=revision)

    markers = {shape.shape_id: shape.marker for shape in diagram.shapes}
    assert markers["res-exact"] is DiagramShapeMarker.EXACT
    assert markers["res-approx"] is DiagramShapeMarker.APPROXIMATE
    assert markers["res-region"] is DiagramShapeMarker.UNAVAILABLE
    assert markers["res-unsupported"] is DiagramShapeMarker.UNAVAILABLE
    assert markers["res-missing"] is DiagramShapeMarker.UNRESOLVED
    assert markers["res-entry-unavailable"] is DiagramShapeMarker.UNRESOLVED

    # Every non-exact marker is visually distinct from every other --
    # never collapsed into one generic "not exact" marker.
    assert len({markers[k] for k in markers}) == 4


def test_exact_shapes_carry_no_marker_detail_but_resolved_target() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    diagram = build_diagram_model(target_model=model, revision=revision)
    exact = next(s for s in diagram.shapes if s.shape_id == "res-exact")
    assert exact.target_service == "cloud-storage"
    assert exact.marker is DiagramShapeMarker.EXACT


# --- no invented shapes -----------------------------------------------------


def test_unresolved_entries_never_invent_a_shape() -> None:
    """An UNRESOLVED target-model entry becomes exactly one real shape --
    backed by the real resource -- never an extra placeholder, never a
    dropped entry, and it never carries a fabricated target_service."""
    model = _mixed_target_model()
    revision = _revision_for(model)
    diagram = build_diagram_model(target_model=model, revision=revision)

    assert len(diagram.shapes) == len(model.resources)
    assert {s.shape_id for s in diagram.shapes} == {r.resource_id for r in model.resources}

    unresolved = [s for s in diagram.shapes if s.marker is DiagramShapeMarker.UNRESOLVED]
    assert len(unresolved) == 2
    for shape in unresolved:
        assert shape.target_service is None
        assert shape.target_provider == ""
        assert shape.detail  # the resolver's own explanation, carried through


def test_building_a_diagram_never_adds_or_drops_shapes_for_any_seed_pattern() -> None:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    for pattern in catalogue.patterns:
        model = generate_target_model(
            tenant_id=TENANT,
            project_id=PROJECT,
            design_id=DESIGN_ID,
            estate=_mixed_estate(),
            pattern=pattern,
            pattern_catalogue_version="2026.11.1",
            mapping_release=_mixed_release(),
            target_provider="gcp",
            parameters=_sample_parameters(pattern),
        )
        revision = _revision_for(model)
        diagram = build_diagram_model(target_model=model, revision=revision)
        assert len(diagram.shapes) == len(model.resources) == len(_mixed_estate())


def _sample_value(parameter_type: PatternParameterType, allowed_values: tuple[str, ...]):
    if parameter_type is PatternParameterType.ENUM:
        return allowed_values[0]
    if parameter_type is PatternParameterType.STRING_LIST:
        return ["sample-value"]
    if parameter_type is PatternParameterType.INTEGER:
        return 1
    if parameter_type is PatternParameterType.BOOLEAN:
        return True
    return "sample"


def _sample_parameters(pattern: Pattern) -> dict[str, object]:
    return {
        parameter.name: _sample_value(parameter.type, parameter.allowed_values)
        for parameter in pattern.parameters
        if parameter.required
    }


# --- revision binding -------------------------------------------------------


def test_build_diagram_model_rejects_a_revision_for_a_different_target_model() -> None:
    model = _mixed_target_model()
    mismatched = _revision_for(model)
    other_model = _mixed_target_model()
    # Mutate nothing -- just prove a revision recorded against a
    # different content_hash is rejected, not silently accepted.
    wrong_revision = RevisionRecord(
        revision_id=mismatched.revision_id,
        tenant_id=mismatched.tenant_id,
        project_id=mismatched.project_id,
        subject_kind=mismatched.subject_kind,
        subject_id=mismatched.subject_id,
        revision_number=mismatched.revision_number,
        content_hash="not-this-models-hash",
        input_versions=mismatched.input_versions,
        created_by=mismatched.created_by,
        created_at=mismatched.created_at,
    )
    with pytest.raises(ValidationError):
        build_diagram_model(target_model=other_model, revision=wrong_revision)


# --- compile_diagram / reproducibility --------------------------------------


def test_compiling_the_same_revision_twice_is_byte_identical() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)

    first = compile_diagram(target_model=model, revision=revision, renderer=FakeDiagramRenderer())
    second = compile_diagram(target_model=model, revision=revision, renderer=FakeDiagramRenderer())

    assert first.artefact_id == second.artefact_id
    assert first.content_hash == second.content_hash
    assert first.rendered_content == second.rendered_content
    assert first.artefact_id != ""


def test_compiling_a_different_revision_produces_a_different_artefact_id() -> None:
    model = _mixed_target_model()
    revision_1 = _revision_for(model, revision_number=1)
    revision_2 = _revision_for(model, revision_number=2)

    first = compile_diagram(target_model=model, revision=revision_1, renderer=FakeDiagramRenderer())
    second = compile_diagram(target_model=model, revision=revision_2, renderer=FakeDiagramRenderer())

    assert first.artefact_id != second.artefact_id


def test_compiling_a_changed_target_model_produces_a_different_artefact() -> None:
    model_a = _mixed_target_model()
    model_b = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=_web_app_pattern(),
        pattern_catalogue_version="2026.11.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters={"compute_platform": "gke", "database_engine": "alloydb"},
    )
    revision_a = _revision_for(model_a)
    revision_b = _revision_for(model_b)

    first = compile_diagram(target_model=model_a, revision=revision_a, renderer=FakeDiagramRenderer())
    second = compile_diagram(target_model=model_b, revision=revision_b, renderer=FakeDiagramRenderer())

    assert first.content_hash != second.content_hash
    assert first.artefact_id != second.artefact_id


def test_compile_diagram_records_the_exact_revision_it_was_compiled_from() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model, revision_number=5)
    artefact = compile_diagram(target_model=model, revision=revision, renderer=FakeDiagramRenderer())

    assert artefact.revision_id == revision.revision_id
    assert artefact.revision_number == 5
    assert artefact.kind == "DIAGRAM"
    assert artefact.design_id == DESIGN_ID


def test_fake_renderer_is_handed_the_exact_structured_model() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    renderer = FakeDiagramRenderer()
    artefact = compile_diagram(target_model=model, revision=revision, renderer=renderer)

    assert len(renderer.rendered) == 1
    assert renderer.rendered[0] is artefact.model


# --- real drawio emitter: no bytes pinned, just "it works" -----------------


def test_real_drawio_emitter_produces_well_formed_xml_without_pinning_bytes() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    artefact = compile_diagram(
        target_model=model, revision=revision, renderer=DrawioXmlDiagramRenderer()
    )
    assert artefact.rendered_content.startswith("<?xml")
    assert "<mxGraphModel>" in artefact.rendered_content
    for shape in artefact.model.shapes:
        assert f"shape-{shape.shape_id}" in artefact.rendered_content


def test_real_drawio_emitter_is_deterministic() -> None:
    model = _mixed_target_model()
    revision = _revision_for(model)
    renderer = DrawioXmlDiagramRenderer()
    first = compile_diagram(target_model=model, revision=revision, renderer=renderer)
    second = compile_diagram(target_model=model, revision=revision, renderer=renderer)
    assert first.rendered_content == second.rendered_content


# --- golden fixture: every seed pattern compiles with a stable shape count -


@pytest.mark.parametrize(
    "pattern",
    load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    ).patterns,
    ids=lambda p: p.id,
)
def test_golden_fixture_every_seed_pattern_compiles_with_the_same_shape_count_and_markers(
    pattern: Pattern,
) -> None:
    model = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=_mixed_estate(),
        pattern=pattern,
        pattern_catalogue_version="2026.11.1",
        mapping_release=_mixed_release(),
        target_provider="gcp",
        parameters=_sample_parameters(pattern),
    )
    revision = _revision_for(model)
    artefact = compile_diagram(target_model=model, revision=revision, renderer=FakeDiagramRenderer())

    assert len(artefact.model.shapes) == 6
    markers = {shape.marker for shape in artefact.model.shapes}
    assert markers == {
        DiagramShapeMarker.EXACT,
        DiagramShapeMarker.APPROXIMATE,
        DiagramShapeMarker.UNAVAILABLE,
        DiagramShapeMarker.UNRESOLVED,
    }

    # Reproducibility holds for every seed pattern too, not only web-app.
    repeat = compile_diagram(target_model=model, revision=revision, renderer=FakeDiagramRenderer())
    assert artefact.artefact_id == repeat.artefact_id
