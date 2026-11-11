import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.events import (
    KNOWN_EVENT_TYPES,
    TOPIC_EVENT_TYPES,
    EventEnvelope,
    OperationClass,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures"

GOLDEN_ENVELOPES = [
    "event_envelope.json",
    "event_envelope_platform.json",
]


@pytest.mark.parametrize("fixture_name", GOLDEN_ENVELOPES)
def test_golden_envelope_validates_and_round_trips(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    envelope = EventEnvelope.model_validate_json(raw)
    reparsed = EventEnvelope.model_validate_json(envelope.model_dump_json())
    assert reparsed == envelope
    assert json.loads(envelope.model_dump_json()) == json.loads(raw)


def test_envelope_is_immutable() -> None:
    envelope = EventEnvelope.model_validate_json(
        (FIXTURES / "event_envelope.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValidationError):
        envelope.producer = "other-worker"


def test_event_version_field_is_enforced() -> None:
    payload = json.loads((FIXTURES / "event_envelope.json").read_text(encoding="utf-8"))
    del payload["event_version"]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


def test_unversioned_event_type_is_rejected() -> None:
    payload = json.loads((FIXTURES / "event_envelope.json").read_text(encoding="utf-8"))
    payload["event_type"] = "assessment.completed"
    with pytest.raises(ValidationError, match="versioned"):
        EventEnvelope.model_validate(payload)


def test_event_type_suffix_must_match_event_version() -> None:
    payload = json.loads((FIXTURES / "event_envelope.json").read_text(encoding="utf-8"))
    payload["event_type"] = "assessment.completed.v2"
    with pytest.raises(ValidationError, match="event_version"):
        EventEnvelope.model_validate(payload)


def test_event_version_must_be_positive() -> None:
    payload = json.loads((FIXTURES / "event_envelope.json").read_text(encoding="utf-8"))
    payload["event_version"] = 0
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


def test_known_event_catalog_matches_spec_topics() -> None:
    assert len(TOPIC_EVENT_TYPES) == 11
    assert len(KNOWN_EVENT_TYPES) == 25
    assert "execution.started.v1" in KNOWN_EVENT_TYPES
    assert "model.call.completed.v1" in KNOWN_EVENT_TYPES


def test_every_known_event_type_validates_as_an_envelope_type() -> None:
    for event_type in sorted(KNOWN_EVENT_TYPES):
        envelope = EventEnvelope(
            event_id="evt-catalog",
            event_type=event_type,
            event_version=int(event_type.rsplit(".v", 1)[1]),
            tenant_id="tenant-1",
            project_id="project-1",
            operation_class=OperationClass.WORKSPACE_MUTATION,
            occurred_at=datetime(2026, 11, 9, 10, 0, tzinfo=UTC),
            correlation_id="corr-1",
            causation_id="op-1",
            producer="test",
            payload={"event_type": event_type},
            evidence_ref=None,
        )
        assert re.search(r"\.v[1-9][0-9]*$", envelope.event_type)


def test_envelope_json_schema_exposes_required_fields() -> None:
    schema = EventEnvelope.model_json_schema()
    assert set(schema["required"]) == {
        "event_id",
        "event_type",
        "event_version",
        "tenant_id",
        "project_id",
        "operation_class",
        "occurred_at",
        "correlation_id",
        "causation_id",
        "producer",
        "payload",
        "evidence_ref",
    }
