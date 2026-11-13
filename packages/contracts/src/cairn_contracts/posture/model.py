from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

ControlVersion = Annotated[str, Field(pattern=r"^\d{4}\.\d{2}\.\d+$")]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ControlDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: RequiredText
    provider: RequiredText
    benchmark: RequiredText
    benchmark_section: RequiredText
    category: RequiredText
    title: RequiredText
    description: RequiredText
    rationale: RequiredText
    remediation: RequiredText
    severity: Severity
    automated: bool


class ControlCatalogueRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: ControlVersion
    released_at: datetime
    status: ReleaseStatus
    controls: tuple[ControlDefinition, ...]

    @field_validator("released_at")
    @classmethod
    def _released_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("released_at must include a timezone")
        return value

    @field_validator("controls")
    @classmethod
    def _controls(cls, value: tuple[ControlDefinition, ...]) -> tuple[ControlDefinition, ...]:
        if not value:
            raise ValueError("a control catalogue release must contain at least one control")
        ids = [control.id for control in value]
        if len(set(ids)) != len(ids):
            raise ValueError("control ids must be unique within a release")
        return value

    @property
    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def is_published(self) -> bool:
        return self.status is ReleaseStatus.PUBLISHED


class ControlVersionReference(BaseModel):
    """An immutable reference from an evaluation to the exact control version it was run against."""

    model_config = ConfigDict(frozen=True)

    control_id: RequiredText
    release_version: ControlVersion


__all__ = [
    "ControlCatalogueRelease",
    "ControlDefinition",
    "ControlVersion",
    "ControlVersionReference",
    "ReleaseStatus",
    "Severity",
]
