from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cairn_contracts.mapping.pattern import (
    Pattern,
    PatternCatalogueRelease,
    PatternCategory,
    PatternReleaseStatus,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures" / "patterns"

# One golden fixture per seeded pattern (R2-03 acceptance: "Parameter
# schema, preconditions, outputs, validation rules"), same style as
# packages/contracts/tests/test_model.py's GOLDEN_FIXTURES.
GOLDEN_PATTERN_FIXTURES = [
    "web-app.json",
    "data-platform.json",
    "ai-app.json",
    "landing-zone.json",
    "event-driven.json",
    "migration.json",
    "resilient-multi-region.json",
]


@pytest.mark.parametrize("fixture_name", GOLDEN_PATTERN_FIXTURES)
def test_golden_pattern_validates_and_round_trips(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    instance = Pattern.model_validate_json(raw)
    reparsed = Pattern.model_validate_json(instance.model_dump_json())
    assert reparsed == instance
    assert json.loads(instance.model_dump_json()) == json.loads(raw)


@pytest.mark.parametrize("fixture_name", GOLDEN_PATTERN_FIXTURES)
def test_golden_pattern_has_real_schema_content(fixture_name: str) -> None:
    """R2-03's acceptance criteria: a real parameter schema, preconditions,
    outputs and validation rules -- not placeholder text."""
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    instance = Pattern.model_validate_json(raw)
    assert len(instance.parameters) >= 1
    assert len(instance.preconditions) >= 1
    assert len(instance.outputs) >= 1
    assert len(instance.validation_rules) >= 1
    assert instance.evidence


@pytest.mark.parametrize("fixture_name", GOLDEN_PATTERN_FIXTURES)
def test_pattern_is_immutable(fixture_name: str) -> None:
    instance = Pattern.model_validate_json(
        (FIXTURES / fixture_name).read_text(encoding="utf-8")
    )
    with pytest.raises(ValidationError):
        instance.name = "changed"  # type: ignore[misc]


def test_golden_fixtures_cover_every_named_category() -> None:
    categories = {
        Pattern.model_validate_json(
            (FIXTURES / fixture_name).read_text(encoding="utf-8")
        ).category
        for fixture_name in GOLDEN_PATTERN_FIXTURES
    }
    assert categories == set(PatternCategory)


def _parameter_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "region",
        "type": "enum",
        "description": "Target region.",
        "required": True,
        "allowed_values": ["europe-west2"],
    }
    payload.update(overrides)
    return payload


def _pattern_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "test-pattern",
        "name": "Test pattern",
        "category": "web_app",
        "description": "A pattern used only in tests.",
        "parameters": [_parameter_payload()],
        "preconditions": ["A precondition."],
        "outputs": [{"capability": "compute", "description": "Some compute."}],
        "validation_rules": [
            {"id": "rule-1", "description": "A rule.", "severity": "error"}
        ],
        "evidence": "test fixture",
    }
    payload.update(overrides)
    return payload


def test_pattern_rejects_duplicate_parameter_names() -> None:
    payload = _pattern_payload(parameters=[_parameter_payload(), _parameter_payload()])
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_pattern_rejects_empty_preconditions() -> None:
    payload = _pattern_payload(preconditions=[])
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_pattern_rejects_empty_outputs() -> None:
    payload = _pattern_payload(outputs=[])
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_pattern_rejects_empty_validation_rules() -> None:
    payload = _pattern_payload(validation_rules=[])
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_pattern_rejects_duplicate_validation_rule_ids() -> None:
    rule = {"id": "dup", "description": "A rule.", "severity": "error"}
    payload = _pattern_payload(validation_rules=[rule, dict(rule)])
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_validation_rule_rejects_unknown_severity() -> None:
    payload = _pattern_payload(
        validation_rules=[{"id": "r", "description": "A rule.", "severity": "critical"}]
    )
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_enum_parameter_requires_allowed_values() -> None:
    payload = _pattern_payload(
        parameters=[_parameter_payload(allowed_values=[])]
    )
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_non_enum_parameter_rejects_allowed_values() -> None:
    payload = _pattern_payload(
        parameters=[
            _parameter_payload(type="boolean", allowed_values=["true", "false"])
        ]
    )
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def test_parameter_with_default_must_not_be_required() -> None:
    payload = _pattern_payload(
        parameters=[_parameter_payload(required=True, default="europe-west2")]
    )
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def _release_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": "2026.11.1",
        "released_at": "2026-11-15T00:00:00Z",
        "status": "DRAFT",
        "patterns": [_pattern_payload()],
    }
    payload.update(overrides)
    return payload


def test_release_round_trips_and_hash_is_stable() -> None:
    release = PatternCatalogueRelease.model_validate(_release_payload())
    reparsed = PatternCatalogueRelease.model_validate_json(release.model_dump_json())
    assert reparsed.content_hash == release.content_hash


def test_release_rejects_empty_patterns() -> None:
    with pytest.raises(ValidationError):
        PatternCatalogueRelease.model_validate(_release_payload(patterns=[]))


def test_release_rejects_duplicate_pattern_ids() -> None:
    payload = _release_payload(patterns=[_pattern_payload(), _pattern_payload()])
    with pytest.raises(ValidationError):
        PatternCatalogueRelease.model_validate(payload)


def test_release_rejects_naive_released_at() -> None:
    with pytest.raises(ValidationError):
        PatternCatalogueRelease.model_validate(
            _release_payload(released_at="2026-11-15T00:00:00")
        )


def test_release_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        PatternCatalogueRelease.model_validate(_release_payload(status="IN_REVIEW"))


def test_is_published_reflects_status() -> None:
    draft = PatternCatalogueRelease.model_validate(_release_payload(status="DRAFT"))
    published = PatternCatalogueRelease.model_validate(_release_payload(status="PUBLISHED"))
    retired = PatternCatalogueRelease.model_validate(_release_payload(status="RETIRED"))
    assert not draft.is_published
    assert published.is_published
    assert not retired.is_published


def test_content_hash_changes_when_patterns_change() -> None:
    base = PatternCatalogueRelease.model_validate(_release_payload())
    changed = PatternCatalogueRelease.model_validate(
        _release_payload(patterns=[_pattern_payload(name="Different name")])
    )
    assert base.content_hash != changed.content_hash


def test_release_is_immutable() -> None:
    release = PatternCatalogueRelease.model_validate(_release_payload())
    with pytest.raises(ValidationError):
        release.status = PatternReleaseStatus.PUBLISHED  # type: ignore[misc]


def test_released_at_accepts_timezone_aware_datetime() -> None:
    release = PatternCatalogueRelease.model_validate(
        _release_payload(released_at=datetime(2026, 11, 15, tzinfo=UTC))
    )
    assert release.released_at.tzinfo is not None
