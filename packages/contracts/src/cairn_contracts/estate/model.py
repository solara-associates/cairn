from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Annotated[float, Field(ge=0, le=1)]
OptionalConfidence = Annotated[float | None, Field(ge=0, le=1)]


class FactStatus(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"


class Outcome(str, Enum):
    PASS = "PASS"
    ACCEPTED_EXCEPTION = "ACCEPTED_EXCEPTION"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


class Disposition(str, Enum):
    REHOST = "REHOST"
    REPLATFORM = "REPLATFORM"
    REFACTOR = "REFACTOR"
    REPURCHASE = "REPURCHASE"
    RETIRE = "RETIRE"
    RETAIN = "RETAIN"


class DependencyKind(str, Enum):
    NETWORK = "NETWORK"
    DATA = "DATA"
    IDENTITY = "IDENTITY"
    API = "API"
    SCHEDULE = "SCHEDULE"
    OTHER = "OTHER"


class DependencyDirection(str, Enum):
    ONE_WAY = "ONE_WAY"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    AMENDED = "AMENDED"
    REJECTED = "REJECTED"


class Equivalence(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_system: str
    source_id: str
    source_version: str | None
    observed_at: datetime | None
    ingested_at: datetime
    parser_version: str
    ingest_run_id: str
    raw_ref: str


class FactValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: Any | None
    status: FactStatus
    source: str
    observed_at: datetime | None
    ingested_at: datetime
    confidence: OptionalConfidence
    mapping_version: str | None
    provenance_ref: str

    @model_validator(mode="after")
    def _enforce_status_semantics(self) -> FactValue:
        if self.value is None and self.status not in {
            FactStatus.UNVERIFIED,
            FactStatus.UNAVAILABLE,
        }:
            raise ValueError("a fact without a value must be UNVERIFIED or UNAVAILABLE")
        if self.status is FactStatus.OBSERVED:
            if self.observed_at is None:
                raise ValueError("an OBSERVED fact must carry an observation time")
            if not self.provenance_ref:
                raise ValueError("an OBSERVED fact must reference provenance")
        if self.status is FactStatus.INFERRED and self.mapping_version is None:
            raise ValueError("an INFERRED fact must state the version used")
        return self


class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    region: str
    service: str
    resource_type: str
    native_id: str
    name: str | None
    tags: dict[str, str]
    facts: dict[str, FactValue]
    provenance: tuple[Provenance, ...]
    status: FactStatus


class Workload(BaseModel):
    model_config = ConfigDict(frozen=True)

    workload_id: str
    tenant_id: str
    project_id: str
    name: str
    environment: str
    owner: str | None
    business_context: str | None
    resource_ids: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    facts: dict[str, FactValue]
    disposition: Disposition | None
    disposition_confidence: OptionalConfidence
    model_version: str
    mapping_version: str


class Dependency(BaseModel):
    model_config = ConfigDict(frozen=True)

    dependency_id: str
    tenant_id: str
    project_id: str
    source_workload_id: str
    target_workload_id: str
    kind: DependencyKind
    direction: DependencyDirection
    status: FactStatus
    provenance: tuple[Provenance, ...]


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    tenant_id: str
    project_id: str
    control_id: str
    control_version: str
    severity: str
    affected_resource_id: str | None
    affected_workload_id: str | None
    outcome: Outcome
    evidence_refs: tuple[str, ...]
    remediation: str | None
    source: str
    status: str


class CostRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    service: str
    region: str
    period_start: datetime
    period_end: datetime
    currency: str
    amount_minor: int
    tags: dict[str, str]
    provenance: Provenance

    @model_validator(mode="after")
    def _enforce_period(self) -> CostRecord:
        if self.period_end <= self.period_start:
            raise ValueError("cost period end must be after period start")
        return self


class DispositionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    tenant_id: str
    project_id: str
    workload_id: str
    disposition: Disposition
    rationale: str
    confidence: Confidence
    status: DecisionStatus
    decided_by: str | None
    decided_at: datetime | None
    model_version: str
    mapping_version: str


class MappingResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    equivalence: Equivalence
    caveat: str | None
    region: str | None
    mapping_version: str
