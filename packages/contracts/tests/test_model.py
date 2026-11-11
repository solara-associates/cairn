import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate import (
    CostRecord,
    DecisionStatus,
    Dependency,
    DependencyDirection,
    DependencyKind,
    Disposition,
    DispositionDecision,
    Equivalence,
    FactStatus,
    FactValue,
    Finding,
    MappingResolution,
    Outcome,
    Provenance,
    Resource,
    Workload,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures"

GOLDEN_FIXTURES = [
    (Provenance, "provenance.json"),
    (FactValue, "fact_value.json"),
    (Resource, "resource.json"),
    (Workload, "workload.json"),
    (Dependency, "dependency.json"),
    (Finding, "finding.json"),
    (CostRecord, "cost_record.json"),
    (DispositionDecision, "disposition_decision.json"),
    (MappingResolution, "mapping_resolution.json"),
]


@pytest.mark.parametrize("model_type,fixture_name", GOLDEN_FIXTURES)
def test_golden_fixture_validates_and_round_trips(
    model_type: type, fixture_name: str
) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    instance = model_type.model_validate_json(raw)
    reparsed = model_type.model_validate_json(instance.model_dump_json())
    assert reparsed == instance
    assert json.loads(instance.model_dump_json()) == json.loads(raw)


@pytest.mark.parametrize("model_type,fixture_name", GOLDEN_FIXTURES)
def test_entities_are_immutable(model_type: type, fixture_name: str) -> None:
    instance = model_type.model_validate_json(
        (FIXTURES / fixture_name).read_text(encoding="utf-8")
    )
    field_name = next(iter(type(instance).model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, field_name, "changed")


def test_unverified_fact_represents_missing_not_zero() -> None:
    fact = FactValue(
        value=None,
        status=FactStatus.UNVERIFIED,
        source="gcp-inventory",
        observed_at=None,
        ingested_at=datetime(2026, 11, 9, 14, 5, tzinfo=UTC),
        confidence=None,
        mapping_version=None,
        provenance_ref="provenance://run-0001/web-1/os_family",
    )
    assert fact.value is None


def test_fact_without_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="UNVERIFIED or UNAVAILABLE"):
        FactValue(
            value=None,
            status=FactStatus.OBSERVED,
            source="gcp-inventory",
            observed_at=None,
            ingested_at=datetime(2026, 11, 9, 14, 5, tzinfo=UTC),
            confidence=None,
            mapping_version=None,
            provenance_ref="",
        )


def test_observed_fact_requires_observation_time() -> None:
    with pytest.raises(ValidationError, match="observation time"):
        FactValue(
            value=4,
            status=FactStatus.OBSERVED,
            source="gcp-inventory",
            observed_at=None,
            ingested_at=datetime(2026, 11, 9, 14, 5, tzinfo=UTC),
            confidence=None,
            mapping_version=None,
            provenance_ref="provenance://run-0001/web-1/cpu_count",
        )


def test_observed_fact_requires_provenance_reference() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        FactValue(
            value=4,
            status=FactStatus.OBSERVED,
            source="gcp-inventory",
            observed_at=datetime(2026, 11, 9, 14, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 11, 9, 14, 5, tzinfo=UTC),
            confidence=None,
            mapping_version=None,
            provenance_ref="",
        )


def test_inferred_fact_requires_mapping_version() -> None:
    with pytest.raises(ValidationError, match="INFERRED"):
        FactValue(
            value="zone:europe-west2",
            status=FactStatus.INFERRED,
            source="region-derivation",
            observed_at=None,
            ingested_at=datetime(2026, 11, 9, 14, 5, tzinfo=UTC),
            confidence=0.7,
            mapping_version=None,
            provenance_ref="",
        )


def test_resource_fact_values_are_validated() -> None:
    raw = json.loads((FIXTURES / "resource.json").read_text(encoding="utf-8"))
    raw["facts"]["cpu_count"]["status"] = "NOT_A_STATUS"
    with pytest.raises(ValidationError):
        Resource.model_validate(raw)


def test_cost_period_must_be_forward() -> None:
    raw = json.loads((FIXTURES / "cost_record.json").read_text(encoding="utf-8"))
    raw["period_end"] = raw["period_start"]
    with pytest.raises(ValidationError, match="period"):
        CostRecord.model_validate(raw)


def test_confidence_bounds_are_enforced() -> None:
    raw = json.loads((FIXTURES / "disposition_decision.json").read_text(encoding="utf-8"))
    raw["confidence"] = 1.5
    with pytest.raises(ValidationError):
        DispositionDecision.model_validate(raw)


def test_derived_entities_record_model_and_mapping_versions() -> None:
    workload = Workload.model_validate_json(
        (FIXTURES / "workload.json").read_text(encoding="utf-8")
    )
    decision = DispositionDecision.model_validate_json(
        (FIXTURES / "disposition_decision.json").read_text(encoding="utf-8")
    )
    assert workload.model_version
    assert workload.mapping_version
    assert decision.model_version
    assert decision.mapping_version
    assert "model_version" in Workload.model_fields
    assert "mapping_version" in Workload.model_fields
    assert "model_version" in DispositionDecision.model_fields
    assert "mapping_version" in DispositionDecision.model_fields
    assert Workload.model_fields["model_version"].is_required()
    assert DispositionDecision.model_fields["mapping_version"].is_required()


def test_enum_members_match_spec() -> None:
    assert {member.value for member in FactStatus} == {
        "OBSERVED",
        "INFERRED",
        "CONFIRMED",
        "APPROXIMATE",
        "UNAVAILABLE",
        "UNVERIFIED",
    }
    assert {member.value for member in Outcome} == {
        "PASS",
        "ACCEPTED_EXCEPTION",
        "MISMATCH",
        "UNVERIFIED",
    }
    assert {member.value for member in Disposition} == {
        "REHOST",
        "REPLATFORM",
        "REFACTOR",
        "REPURCHASE",
        "RETIRE",
        "RETAIN",
    }
    assert {member.value for member in DependencyKind} == {
        "NETWORK",
        "DATA",
        "IDENTITY",
        "API",
        "SCHEDULE",
        "OTHER",
    }
    assert {member.value for member in DependencyDirection} == {
        "ONE_WAY",
        "BIDIRECTIONAL",
    }
    assert {member.value for member in DecisionStatus} == {
        "PROPOSED",
        "ACCEPTED",
        "AMENDED",
        "REJECTED",
    }
    assert {member.value for member in Equivalence} == {
        "EXACT",
        "APPROXIMATE",
        "UNAVAILABLE",
        "UNSUPPORTED",
    }


def test_unknown_enum_value_is_rejected() -> None:
    raw = json.loads((FIXTURES / "dependency.json").read_text(encoding="utf-8"))
    raw["kind"] = "SNEAKERNET"
    with pytest.raises(ValidationError):
        Dependency.model_validate(raw)
