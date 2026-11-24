"""R2-03: the pattern catalogue schema (spec 5.4's ``PatternRepository`` port,
backed by spec 7.4's "7 patterns" seed dataset; CLOUD-ARCHITECTURE-
PATTERNS.md Part B/C is the grounding evidence for each seed pattern's
shape).

Patterns are versioned and immutable once published, the same discipline
spec 7.3 states for mapping releases ("Published versions are immutable.
Corrections create a new version."). They do **not** carry ADR-004's
propose/review/approve/publish/retire workflow: nothing in spec 7 or the
R2-03 backlog row ("Parameter schema, preconditions, outputs, validation
rules") asks for one, and ``PatternRepository``'s row in spec 5.4 does not
reference ADR-004 the way the mapping registry's R2-01 workflow does. So
``PatternReleaseStatus`` below is a plain three-state status
(DRAFT/PUBLISHED/RETIRED) distinct from ``cairn_contracts.mapping.model.
ReleaseStatus``, which carries ADR-004's IN_REVIEW/APPROVED states that do
not apply here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PatternVersion = Annotated[str, Field(pattern=r"^\d{4}\.\d{2}\.\d+$")]
RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PatternReleaseStatus(str, Enum):
    """Patterns' own, deliberately simpler status set -- no ADR-004 workflow.

    ``DRAFT`` -> ``PUBLISHED`` -> ``RETIRED``, with ``PUBLISHED`` immutable
    and ``RETIRED`` terminal, matching spec 7.3's general registry
    immutability rule without the mapping registry's review states.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PatternCategory(str, Enum):
    """Spec 7.4's named seed categories for the pattern catalogue."""

    WEB_APP = "web_app"
    DATA_PLATFORM = "data_platform"
    AI_APP = "ai_app"
    LANDING_ZONE = "landing_zone"
    EVENT_DRIVEN = "event_driven"
    MIGRATION = "migration"
    RESILIENT_MULTI_REGION = "resilient_multi_region"


class PatternParameterType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    STRING_LIST = "string_list"


class PatternParameter(BaseModel):
    """One entry in a pattern's parameter schema."""

    model_config = ConfigDict(frozen=True)

    name: RequiredText
    type: PatternParameterType
    description: RequiredText
    required: bool = True
    default: Any | None = None
    allowed_values: tuple[RequiredText, ...] = ()

    @model_validator(mode="after")
    def _default_implies_optional(self) -> PatternParameter:
        if self.default is not None and self.required:
            raise ValueError("a parameter with a default value must not be marked required")
        return self

    @model_validator(mode="after")
    def _enum_requires_allowed_values(self) -> PatternParameter:
        if self.type is PatternParameterType.ENUM and not self.allowed_values:
            raise ValueError("an ENUM parameter must declare allowed_values")
        if self.type is not PatternParameterType.ENUM and self.allowed_values:
            raise ValueError("allowed_values is only meaningful for an ENUM parameter")
        return self


class PatternOutput(BaseModel):
    """One capability this pattern produces once its parameters are resolved."""

    model_config = ConfigDict(frozen=True)

    capability: RequiredText
    description: RequiredText


class PatternValidationRule(BaseModel):
    """A rule the design module checks against a pattern's resolved parameters."""

    model_config = ConfigDict(frozen=True)

    id: RequiredText
    description: RequiredText
    severity: RequiredText

    @field_validator("severity")
    @classmethod
    def _severity_is_known(cls, value: str) -> str:
        if value not in ("error", "warning"):
            raise ValueError("severity must be 'error' or 'warning'")
        return value


class Pattern(BaseModel):
    """A single architecture pattern: parameter schema, preconditions,
    outputs and validation rules (R2-03's acceptance criteria), per spec
    5.4's ``PatternRepository`` port and grounded in CLOUD-ARCHITECTURE-
    PATTERNS.md's catalogue.
    """

    model_config = ConfigDict(frozen=True)

    id: RequiredText
    name: RequiredText
    category: PatternCategory
    description: RequiredText
    parameters: tuple[PatternParameter, ...]
    preconditions: tuple[RequiredText, ...]
    outputs: tuple[PatternOutput, ...]
    validation_rules: tuple[PatternValidationRule, ...]
    evidence: RequiredText

    @field_validator("parameters")
    @classmethod
    def _unique_parameter_names(
        cls, value: tuple[PatternParameter, ...]
    ) -> tuple[PatternParameter, ...]:
        names = [parameter.name for parameter in value]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique within a pattern")
        return value

    @field_validator("preconditions")
    @classmethod
    def _preconditions_are_real(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("a pattern must declare at least one precondition")
        return value

    @field_validator("outputs")
    @classmethod
    def _outputs_are_real(cls, value: tuple[PatternOutput, ...]) -> tuple[PatternOutput, ...]:
        if not value:
            raise ValueError("a pattern must declare at least one output")
        return value

    @field_validator("validation_rules")
    @classmethod
    def _validation_rules_are_real(
        cls, value: tuple[PatternValidationRule, ...]
    ) -> tuple[PatternValidationRule, ...]:
        if not value:
            raise ValueError("a pattern must declare at least one validation rule")
        ids = [rule.id for rule in value]
        if len(set(ids)) != len(ids):
            raise ValueError("validation rule ids must be unique within a pattern")
        return value


class PatternCatalogueRelease(BaseModel):
    """A versioned, immutable-once-published set of patterns -- the same
    discipline as ``cairn_contracts.mapping.model.MappingRelease``, minus
    the ADR-004 review workflow (see module docstring).
    """

    model_config = ConfigDict(frozen=True)

    version: PatternVersion
    released_at: datetime
    status: PatternReleaseStatus
    patterns: tuple[Pattern, ...]

    @field_validator("released_at")
    @classmethod
    def _released_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("released_at must include a timezone")
        return value

    @field_validator("patterns")
    @classmethod
    def _patterns(cls, value: tuple[Pattern, ...]) -> tuple[Pattern, ...]:
        if not value:
            raise ValueError("a pattern catalogue release must contain at least one pattern")
        ids = [pattern.id for pattern in value]
        if len(set(ids)) != len(ids):
            raise ValueError("pattern ids must be unique within a release")
        return value

    @property
    def content_hash(self) -> str:
        """Hash of this release's content, deliberately excluding ``status``.

        Unlike ``MappingRelease`` (whose status transitions live on a
        separate workflow record, never on the hashed model itself),
        ``PatternCatalogueRelease.status`` *is* mutated in place by
        ``InMemoryPatternRepository.publish``/``retire`` -- there is no
        ADR-004 workflow record here. Excluding ``status`` keeps the hash
        stable across DRAFT -> PUBLISHED -> RETIRED, so "immutable once
        published" can mean "the same content_hash", not "the same status".
        """
        payload = self.model_dump(mode="json", exclude={"status"})
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def is_published(self) -> bool:
        return self.status is PatternReleaseStatus.PUBLISHED


__all__ = [
    "Pattern",
    "PatternCatalogueRelease",
    "PatternCategory",
    "PatternOutput",
    "PatternParameter",
    "PatternParameterType",
    "PatternReleaseStatus",
    "PatternValidationRule",
    "PatternVersion",
]
