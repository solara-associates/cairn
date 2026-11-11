from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from itertools import chain
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOPIC_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "cairn.ingestion": (
        "ingestion.requested.v1",
        "ingestion.completed.v1",
        "ingestion.failed.v1",
    ),
    "cairn.estate": ("estate.normalized.v1", "estate.fact.confirmed.v1"),
    "cairn.assessment": ("assessment.requested.v1", "assessment.completed.v1"),
    "cairn.posture": ("finding.recorded.v1", "exception.accepted.v1"),
    "cairn.cost": ("cost.imported.v1", "baseline.created.v1", "scenario.created.v1"),
    "cairn.mapping": ("mapping.release.published.v1", "mapping.proposed.v1"),
    "cairn.design": (
        "design.generated.v1",
        "plan.created.v1",
        "plan.revised.v1",
    ),
    "cairn.approval": ("approval.requested.v1", "approval.decided.v1"),
    "cairn.execution": (
        "execution.started.v1",
        "execution.completed.v1",
        "execution.failed.v1",
    ),
    "cairn.evidence": ("evidence.sealed.v1", "evidence.verified.v1"),
    "cairn.ai": ("model.call.completed.v1",),
}

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    chain.from_iterable(TOPIC_EVENT_TYPES.values())
)

_EVENT_TYPE_PATTERN = re.compile(
    r"^(?P<name>[a-z0-9_]+(?:\.[a-z0-9_-]+)*)\.v(?P<version>[1-9][0-9]*)$"
)


class OperationClass(str, Enum):
    READ = "READ"
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"
    GOVERNED_ENV_MUTATION = "GOVERNED_ENV_MUTATION"


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: str
    event_version: int = Field(ge=1)
    tenant_id: str | None
    project_id: str | None
    operation_class: OperationClass
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None
    producer: str
    payload: dict[str, Any]
    evidence_ref: str | None

    @model_validator(mode="after")
    def _enforce_versioned_type(self) -> EventEnvelope:
        match = _EVENT_TYPE_PATTERN.match(self.event_type)
        if match is None:
            raise ValueError("event_type must be versioned, for example assessment.completed.v1")
        if int(match.group("version")) != self.event_version:
            raise ValueError("event_version must match the version suffix in event_type")
        return self
