"""R1-13: a versioned, immutable GCP price-list snapshot.

Mirrors ``cairn_contracts.mapping``'s ``MappingRelease``/``MappingEntry``
immutable-release shape exactly (R0-14's mechanism, reused rather than
reinvented): a release is published once, is content-addressed, and a
later publish under the same version with different content is rejected
-- a correction requires a new version.
"""

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

PriceListVersion = Annotated[str, Field(pattern=r"^\d{4}\.\d{2}\.\d+$")]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PriceListEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: RequiredText
    provider: RequiredText
    service: RequiredText
    sku: RequiredText
    region: RequiredText
    unit: RequiredText
    unit_price_minor: int = Field(ge=0)
    currency: Annotated[str, StringConstraints(min_length=3, max_length=3)]

    @field_validator("currency")
    @classmethod
    def _currency_is_uppercase(cls, value: str) -> str:
        if not value.isupper():
            raise ValueError("currency must be a 3-letter uppercase ISO 4217 code")
        return value


class PriceListRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: PriceListVersion
    released_at: datetime
    status: ReleaseStatus
    entries: tuple[PriceListEntry, ...]

    @field_validator("released_at")
    @classmethod
    def _released_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("released_at must include a timezone")
        return value

    @field_validator("entries")
    @classmethod
    def _entries(cls, value: tuple[PriceListEntry, ...]) -> tuple[PriceListEntry, ...]:
        if not value:
            raise ValueError("a price list release must contain at least one entry")
        ids = [entry.id for entry in value]
        if len(set(ids)) != len(ids):
            raise ValueError("price list entry ids must be unique within a release")
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
    "PriceListEntry",
    "PriceListRelease",
    "PriceListVersion",
    "ReleaseStatus",
]
