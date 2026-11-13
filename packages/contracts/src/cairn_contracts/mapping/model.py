from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from cairn_contracts.estate import Equivalence

MappingVersion = Annotated[str, Field(pattern=r"^\d{4}\.\d{2}\.\d+$")]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class MappingEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: RequiredText
    source_provider: RequiredText
    source_service: RequiredText
    target_provider: RequiredText
    target_service: RequiredText | None = None
    equivalence: Equivalence
    caveat: RequiredText | None = None
    regions: tuple[RequiredText, ...] = ()
    evidence: RequiredText
    effective_from: date | None = None

    @field_validator("regions")
    @classmethod
    def _regions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("regions must be unique")
        return value

    @model_validator(mode="after")
    def _validate_equivalence(self) -> MappingEntry:
        if (
            self.equivalence in (Equivalence.EXACT, Equivalence.APPROXIMATE)
            and self.target_service is None
        ):
            raise ValueError("target_service is required for exact or approximate mappings")
        if self.equivalence is not Equivalence.EXACT and self.caveat is None:
            raise ValueError("caveat is required for every non-exact mapping")
        return self


class MappingRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: MappingVersion
    released_at: datetime
    status: ReleaseStatus
    entries: tuple[MappingEntry, ...]

    @field_validator("released_at")
    @classmethod
    def _released_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("released_at must include a timezone")
        return value

    @field_validator("entries")
    @classmethod
    def _entries(cls, value: tuple[MappingEntry, ...]) -> tuple[MappingEntry, ...]:
        if not value:
            raise ValueError("a mapping release must contain at least one entry")
        ids = [entry.id for entry in value]
        if len(set(ids)) != len(ids):
            raise ValueError("mapping entry ids must be unique within a release")
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


__all__ = [
    "MappingEntry",
    "MappingRelease",
    "MappingVersion",
    "ReleaseStatus",
]
