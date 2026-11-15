"""R2-04: the target model generator.

Determinism (same inputs -> identical content hash), version recording,
revision immutability/monotonicity on ``subject_revision``
(``subject_kind="design"``), and correct surfacing of unresolved/
unavailable mappings are this story's acceptance criteria (spec §16's
R2-04 row). A golden-fixture test runs every seed pattern from 701
against a synthetic estate to prove every pattern can generate without
raising.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate import Equivalence, FactStatus, Resource
from cairn_contracts.mapping import MappingEntry, MappingRelease, ReleaseStatus
from cairn_contracts.mapping.pattern import Pattern, PatternParameterType
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.design import (
    DESIGN_SUBJECT_KIND,
    FakeDesignRevisionRepository,
    TargetResourceStatus,
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


def _context(tenant: str = TENANT) -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=None,
        actor_id="alice",
        actor_roles=(),
        correlation_id="corr-1",
    )


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


def _generate(**overrides: object) -> object:
    pattern = overrides.pop("pattern", _web_app_pattern())
    release = overrides.pop("mapping_release", _release())
    estate = overrides.pop("estate", (_resource(),))
    parameters = overrides.pop(
        "parameters",
        {"compute_platform": "cloud_run", "database_engine": "cloud_sql_postgres"},
    )
    kwargs = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "design_id": DESIGN_ID,
        "estate": estate,
        "pattern": pattern,
        "pattern_catalogue_version": "2026.11.1",
        "mapping_release": release,
        "target_provider": "gcp",
        "parameters": parameters,
    }
    kwargs.update(overrides)
    return generate_target_model(**kwargs)


# --- determinism -------------------------------------------------------


def test_same_inputs_produce_identical_content_hash() -> None:
    first = _generate()
    second = _generate()
    assert first.content_hash == second.content_hash
    assert first.content_hash != ""


def test_resource_order_does_not_affect_content_hash() -> None:
    a = _resource(resource_id="res-a")
    b = _resource(resource_id="res-b")
    forward = _generate(estate=(a, b))
    backward = _generate(estate=(b, a))
    assert forward.content_hash == backward.content_hash


def test_changed_parameters_produce_a_different_content_hash() -> None:
    first = _generate()
    second = _generate(
        parameters={"compute_platform": "gke", "database_engine": "alloydb"}
    )
    assert first.content_hash != second.content_hash


# --- version recording ---------------------------------------------------


def test_target_model_records_the_exact_versions_used() -> None:
    model = _generate()
    assert model.mapping_release_version == "2026.11.1"
    assert model.pattern_catalogue_version == "2026.11.1"
    assert model.pattern_id == "web-app"
    assert dict(model.parameters) == {
        "compute_platform": "cloud_run",
        "database_engine": "cloud_sql_postgres",
        "enable_cache": False,
        "custom_domain": None,
    }


def test_revision_input_versions_carry_mapping_pattern_and_parameters() -> None:
    model = _generate()
    repo = FakeDesignRevisionRepository()
    with tenant_scope(_context()):
        record = repo.create_revision(design_id=DESIGN_ID, target_model=model, created_by="alice")

    input_versions = dict(record.input_versions)
    assert input_versions["mapping_release_version"] == "2026.11.1"
    assert input_versions["pattern_catalogue_version"] == "2026.11.1"
    assert input_versions["pattern_id"] == "web-app"
    assert "cloud_run" in input_versions["parameters"]


# --- revision persistence: monotonic, append-only -------------------------


def test_first_generation_is_revision_number_one() -> None:
    repo = FakeDesignRevisionRepository()
    model = _generate()
    with tenant_scope(_context()):
        record = repo.create_revision(design_id=DESIGN_ID, target_model=model, created_by="alice")
    assert record.revision_number == 1
    assert record.subject_kind == DESIGN_SUBJECT_KIND
    assert record.subject_id == DESIGN_ID
    assert record.content_hash == model.content_hash


def test_regeneration_with_changed_parameters_creates_revision_two_not_a_mutation() -> None:
    repo = FakeDesignRevisionRepository()
    first_model = _generate()
    second_model = _generate(
        parameters={"compute_platform": "gke", "database_engine": "alloydb"}
    )
    with tenant_scope(_context()):
        first = repo.create_revision(
            design_id=DESIGN_ID, target_model=first_model, created_by="alice"
        )
        second = repo.create_revision(
            design_id=DESIGN_ID, target_model=second_model, created_by="alice"
        )
        revisions = repo.list_revisions(
            tenant_id=TENANT, project_id=PROJECT, design_id=DESIGN_ID
        )

    assert second.revision_number == 2
    assert second.content_hash != first.content_hash
    assert [r.revision_number for r in revisions] == [1, 2]
    # the prior revision is still exactly as it was created -- never mutated.
    assert revisions[0].content_hash == first.content_hash
    assert revisions[0].revision_number == 1


def test_latest_revision_reflects_the_most_recent_generation() -> None:
    repo = FakeDesignRevisionRepository()
    second_model = _generate(
        parameters={"compute_platform": "gke", "database_engine": "alloydb"}
    )
    with tenant_scope(_context()):
        repo.create_revision(design_id=DESIGN_ID, target_model=_generate(), created_by="alice")
        repo.create_revision(design_id=DESIGN_ID, target_model=second_model, created_by="alice")
        latest = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, design_id=DESIGN_ID)

    assert latest is not None
    assert latest.revision_number == 2
    assert latest.content_hash == second_model.content_hash


def test_a_design_with_no_revisions_yet_has_no_latest() -> None:
    repo = FakeDesignRevisionRepository()
    with tenant_scope(_context()):
        assert repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, design_id=DESIGN_ID) is None


def test_revisions_for_distinct_designs_do_not_collide() -> None:
    repo = FakeDesignRevisionRepository()
    with tenant_scope(_context()):
        repo.create_revision(design_id="design-a", target_model=_generate(), created_by="alice")
        repo.create_revision(design_id="design-b", target_model=_generate(), created_by="alice")
        a = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, design_id="design-a")
        b = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, design_id="design-b")
    assert a.revision_number == 1
    assert b.revision_number == 1


# --- unresolved / unavailable mappings are surfaced, never dropped --------


def test_resource_with_no_mapping_entry_is_surfaced_as_unresolved() -> None:
    release = _release(_entry(source_service="s3"))
    resource = _resource(resource_id="res-1", service="rds")  # no entry maps "rds"
    model = _generate(estate=(resource,), mapping_release=release)

    assert len(model.resources) == 1
    entry = model.resources[0]
    assert entry.status is TargetResourceStatus.UNRESOLVED
    assert entry.resolution is None
    assert "no mapping" in entry.reason
    assert model.unresolved_resource_ids == ("res-1",)


def test_resource_with_an_unavailable_equivalence_is_surfaced_not_substituted() -> None:
    release = _release(
        _entry(
            source_service="s3",
            equivalence=Equivalence.UNAVAILABLE,
            caveat="No equivalent service exists on this target",
        )
    )
    resource = _resource(resource_id="res-1", service="s3")
    model = _generate(estate=(resource,), mapping_release=release)

    entry = model.resources[0]
    assert entry.status is TargetResourceStatus.UNRESOLVED
    assert entry.resolution is None
    assert entry.reason == "No equivalent service exists on this target"


def test_resolved_and_unresolved_resources_coexist_in_one_generation() -> None:
    release = _release(_entry(source_service="s3"))
    resolved = _resource(resource_id="res-resolved", service="s3")
    unresolved = _resource(resource_id="res-unresolved", service="rds")
    model = _generate(estate=(resolved, unresolved), mapping_release=release)

    by_id = {entry.resource_id: entry for entry in model.resources}
    assert by_id["res-resolved"].status is TargetResourceStatus.RESOLVED
    assert by_id["res-resolved"].resolution is not None
    assert by_id["res-unresolved"].status is TargetResourceStatus.UNRESOLVED
    assert model.unresolved_resource_ids == ("res-unresolved",)


# --- parameter handling ----------------------------------------------------


def test_unknown_parameter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not declare"):
        _generate(
            parameters={
                "compute_platform": "cloud_run",
                "database_engine": "cloud_sql_postgres",
                "nonexistent": "x",
            }
        )


def test_missing_required_parameter_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires parameter"):
        _generate(parameters={"compute_platform": "cloud_run"})


def test_missing_optional_parameter_is_filled_with_its_default() -> None:
    model = _generate(
        parameters={"compute_platform": "cloud_run", "database_engine": "alloydb"}
    )
    assert dict(model.parameters)["enable_cache"] is False


def test_invalid_enum_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be one of"):
        _generate(
            parameters={"compute_platform": "not-a-real-platform", "database_engine": "alloydb"}
        )


def test_wrong_parameter_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be of type"):
        _generate(
            parameters={
                "compute_platform": "cloud_run",
                "database_engine": "alloydb",
                "enable_cache": "yes",
            }
        )


# --- golden fixture: every seed pattern generates without raising --------


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


def _all_seed_patterns() -> list[Pattern]:
    catalogue = load_pattern_catalogue(
        PATTERNS_DIR, version="2026.11.1", released_at=datetime(2026, 11, 15, tzinfo=UTC)
    )
    return list(catalogue.patterns)


@pytest.mark.parametrize("pattern", _all_seed_patterns(), ids=lambda p: p.id)
def test_every_seed_pattern_generates_against_a_synthetic_estate(pattern: Pattern) -> None:
    release = _release(_entry())
    model = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=(_resource(),),
        pattern=pattern,
        pattern_catalogue_version="2026.11.1",
        mapping_release=release,
        target_provider="gcp",
        parameters=_sample_parameters(pattern),
    )
    assert model.pattern_id == pattern.id
    assert len(model.resources) == 1
    # determinism holds for every seed pattern too, not only web-app.
    repeat = generate_target_model(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id=DESIGN_ID,
        estate=(_resource(),),
        pattern=pattern,
        pattern_catalogue_version="2026.11.1",
        mapping_release=release,
        target_provider="gcp",
        parameters=_sample_parameters(pattern),
    )
    assert model.content_hash == repeat.content_hash
