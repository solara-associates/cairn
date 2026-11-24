"""R5-05b: estate-data-level residency sweeps.

ADR-016 commits CAIRN to one launch jurisdiction pack (UK, deployed in
``europe-west2``) and requires every assessment to record the pack and
version used, with no compliance claim unbacked by a pack, a control
version and an evidence record. ``docs/residency/uk-residency-matrix.md``
already checks that ADR-016's residency facts hold at the
*infrastructure* level -- ``tests/conformance/test_uk_residency.py``
inspects this repo's own Terraform. That check says nothing about a
*customer's estate data* -- the workloads CAIRN ingests and assesses for a
tenant. This module is that different, estate-data-level check: given a
canonical estate snapshot (R1-06/R1-07's ``Workload`` model), flag any
workload whose own declared region falls outside the jurisdiction pack's
residency constraint, and seal the sweep's result as evidence through
R0-11/R1-17's existing ``cairn_kernel.evidence.seal_evidence`` -- the same
machinery every other governed decision in this codebase uses, reused
here exactly as R3-06's ``cairn_modules.transformation.evidence`` already
reuses it, not reinvented.

No real inventory call against any cloud project is made or implied here
-- the brief is explicit that a real sweep against ``<gcp-project-id>``/
``-exec`` is out of this unit's scope. Every sweep in this module runs
against a caller-supplied, already-canonical ``Workload`` sequence (a
fixture in tests; whatever the estate's own ingestion/assessment pipeline
has already produced, in production).

Judgement call -- how a workload's region is represented:
``cairn_contracts.estate.model.Workload`` does not carry a region field of
its own (only ``Resource`` does, via its ``region: str`` field). Adding one
to the canonical contract would be a shared-contract change reaching far
beyond this unit's scope, for a fact the model already has a general
mechanism for: the fact-sourcing journey every other derived workload-level
fact already uses (``cairn_modules.estate.normalize``'s ``_build_facts``,
R1-07's grouping module). This sweep reads a workload's region the same
way: as an entry in ``Workload.facts`` keyed ``"region"`` (``REGION_FACT_KEY``
below), carrying the usual ``FactValue`` status/provenance envelope. A
caller that has resolved a workload's region from its underlying
resources' own canonical ``region`` fields is expected to have written it
there already; this module does not reach through ``resource_ids`` to
recompute it, the same way no other workload-level fact consumer in this
codebase recomputes a fact from resources at read time.

Fail-closed, never fail-silent: a workload whose region fact is missing,
``UNVERIFIED`` or ``UNAVAILABLE`` is flagged as a finding in its own right
(``ResidencyFindingReason.REGION_UNKNOWN``) rather than treated as
"presumably fine" -- the same fail-closed stance R5-05a's own
``FailoverOutcome.UNGOVERNED`` already takes for a workload with no
declared failover policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from datetime import datetime
from enum import Enum

from cairn_contracts.estate.model import FactStatus, Workload
from cairn_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceInput,
    EvidenceOutput,
    EvidenceSigner,
    EvidenceSubject,
    ProvenanceRecord,
    payload_hash,
    seal_evidence,
)
from pydantic import BaseModel, ConfigDict

#: The ``Workload.facts`` key this sweep reads a workload's declared
#: region from. See the module docstring's judgement-call note.
REGION_FACT_KEY = "region"

#: ADR-016: CAIRN launches with the UK jurisdiction pack, deployed in
#: ``europe-west2``, and that pack's residency constraint is the one
#: region data may reside in.
UK_PACK_ID = "uk"
UK_PACK_VERSION = "2026.11.0"
UK_ALLOWED_REGIONS: frozenset[str] = frozenset({"europe-west2"})

EVIDENCE_SUBJECT_KIND = "residency_sweep"
PRODUCER = {"name": "cairn-sovereignty-residency-sweep", "version": "r5-05b-v1"}


class ResidencyFindingReason(str, Enum):
    #: The workload's declared region is a real, known region, but it is
    #: not one of the jurisdiction pack's allowed regions.
    OUT_OF_REGION = "OUT_OF_REGION"
    #: The workload carries no usable region fact at all (missing,
    #: ``UNVERIFIED`` or ``UNAVAILABLE``) -- fails closed as a finding
    #: rather than being treated as compliant by default.
    REGION_UNKNOWN = "REGION_UNKNOWN"


class ResidencySweepStatus(str, Enum):
    #: Every workload swept declared a region inside the constraint.
    #: Still an explicit, sealed outcome -- never indistinguishable from
    #: "the sweep never ran".
    CLEAN = "CLEAN"
    #: At least one workload was flagged.
    FINDINGS = "FINDINGS"


class ResidencyFinding(BaseModel):
    """One workload flagged by a residency sweep, named and attributable."""

    model_config = ConfigDict(frozen=True)

    workload_id: str
    workload_name: str
    tenant_id: str
    project_id: str
    declared_region: str | None
    reason: ResidencyFindingReason
    detail: str


class ResidencySweepResult(BaseModel):
    """The outcome of sweeping one estate snapshot against one
    jurisdiction pack's residency constraint.

    ``status`` is an explicit, typed outcome field: a clean sweep sets it
    to ``CLEAN`` with an empty ``findings`` tuple, never leaving the
    result ambiguous with "no result was produced at all".
    """

    model_config = ConfigDict(frozen=True)

    status: ResidencySweepStatus
    pack_id: str
    pack_version: str
    allowed_regions: tuple[str, ...]
    workloads_checked: int
    findings: tuple[ResidencyFinding, ...]


def sweep_estate_residency(
    workloads: Sequence[Workload],
    *,
    allowed_regions: AbstractSet[str] = UK_ALLOWED_REGIONS,
    pack_id: str = UK_PACK_ID,
    pack_version: str = UK_PACK_VERSION,
) -> ResidencySweepResult:
    """Sweep a canonical estate snapshot for workloads declared outside
    ``allowed_regions``.

    Every workload in ``workloads`` is checked, in a stable
    (``workload_id``-sorted) order; none is silently skipped. Zero
    findings still returns a result with ``status=CLEAN`` -- the caller
    always has an explicit outcome to seal, never nothing.
    """

    findings: list[ResidencyFinding] = []
    for workload in sorted(workloads, key=lambda w: w.workload_id):
        region_fact = workload.facts.get(REGION_FACT_KEY)
        if (
            region_fact is None
            or region_fact.value is None
            or region_fact.status in {FactStatus.UNVERIFIED, FactStatus.UNAVAILABLE}
        ):
            findings.append(
                ResidencyFinding(
                    workload_id=workload.workload_id,
                    workload_name=workload.name,
                    tenant_id=workload.tenant_id,
                    project_id=workload.project_id,
                    declared_region=None,
                    reason=ResidencyFindingReason.REGION_UNKNOWN,
                    detail=(
                        f"workload {workload.workload_id!r} ({workload.name}) carries no "
                        "usable region fact -- fails closed, not presumed in-region"
                    ),
                )
            )
            continue

        region = str(region_fact.value)
        if region not in allowed_regions:
            findings.append(
                ResidencyFinding(
                    workload_id=workload.workload_id,
                    workload_name=workload.name,
                    tenant_id=workload.tenant_id,
                    project_id=workload.project_id,
                    declared_region=region,
                    reason=ResidencyFindingReason.OUT_OF_REGION,
                    detail=(
                        f"workload {workload.workload_id!r} ({workload.name}) declares region "
                        f"{region!r}, outside the {pack_id!r} pack's allowed region(s) "
                        f"{sorted(allowed_regions)!r}"
                    ),
                )
            )

    status = ResidencySweepStatus.CLEAN if not findings else ResidencySweepStatus.FINDINGS
    return ResidencySweepResult(
        status=status,
        pack_id=pack_id,
        pack_version=pack_version,
        allowed_regions=tuple(sorted(allowed_regions)),
        workloads_checked=len(workloads),
        findings=tuple(findings),
    )


def _finding_payload(finding: ResidencyFinding) -> dict[str, object]:
    return {
        "workload_id": finding.workload_id,
        "workload_name": finding.workload_name,
        "tenant_id": finding.tenant_id,
        "project_id": finding.project_id,
        "declared_region": finding.declared_region,
        "reason": finding.reason.value,
        "detail": finding.detail,
    }


def _result_payload(result: ResidencySweepResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "pack_id": result.pack_id,
        "pack_version": result.pack_version,
        "allowed_regions": list(result.allowed_regions),
        "workloads_checked": result.workloads_checked,
        "findings": [_finding_payload(finding) for finding in result.findings],
    }


def _workload_region_payload(workload: Workload) -> dict[str, object]:
    region_fact = workload.facts.get(REGION_FACT_KEY)
    return {
        "workload_id": workload.workload_id,
        "region": None if region_fact is None else region_fact.value,
        "status": None if region_fact is None else region_fact.status.value,
    }


def build_residency_sweep_evidence_package(
    result: ResidencySweepResult,
    workloads: Sequence[Workload],
    *,
    package_id: str,
    tenant_id: str,
    project_id: str,
    signer: EvidenceSigner,
    created_at: datetime,
    previous_hash: str | None = None,
) -> EvidenceEnvelope:
    """Seal one signed evidence record for a completed residency sweep,
    through R0-11/R1-17's existing ``seal_evidence`` -- no new hashing,
    signing, canonicalization or chain logic.

    Every sweep run produces a sealed record, clean or not: ``outcome``
    is ``"PASS"`` for a clean sweep and ``"FAIL"`` when any workload was
    flagged, so a reader of the evidence chain never has to guess whether
    "no findings" means "nothing to report" or "nothing ran".
    """

    subject = EvidenceSubject(kind=EVIDENCE_SUBJECT_KIND, id=project_id)

    inputs = tuple(
        EvidenceInput(
            kind="workload_region",
            ref=workload.workload_id,
            hash=payload_hash(_workload_region_payload(workload)),
        )
        for workload in sorted(workloads, key=lambda w: w.workload_id)
    )

    provenance = (
        ProvenanceRecord(
            fact_ref=f"residency_sweep:{package_id}",
            source="cairn-sovereignty-residency-sweep",
            observed_at=created_at,
        ),
    )

    outputs = (
        EvidenceOutput(
            kind="residency_sweep_result",
            ref=package_id,
            hash=payload_hash(_result_payload(result)),
        ),
    )

    outcome = "PASS" if result.status is ResidencySweepStatus.CLEAN else "FAIL"

    return seal_evidence(
        signer=signer,
        package_id=package_id,
        tenant_id=tenant_id,
        project_id=project_id,
        subject=subject,
        created_at=created_at,
        producer=PRODUCER,
        inputs=inputs,
        provenance=provenance,
        versions={
            "jurisdiction_pack_id": result.pack_id,
            "jurisdiction_pack_version": result.pack_version,
        },
        outputs=outputs,
        outcome=outcome,
        previous_hash=previous_hash,
    )


def region_fact(
    value: str, *, source: str, observed_at: datetime, provenance_ref: str
) -> Mapping[str, object]:
    """Not used by this module itself -- a small convenience left for
    callers/tests building a ``Workload.facts`` region entry without
    repeating ``FactValue``'s full constructor each time. Returns a plain
    mapping of constructor kwargs, not a ``FactValue``, so this module
    carries no implicit opinion about a caller's own ``ingested_at``.
    """

    return {
        "value": value,
        "status": FactStatus.OBSERVED,
        "source": source,
        "observed_at": observed_at,
        "confidence": None,
        "mapping_version": None,
        "provenance_ref": provenance_ref,
    }


__all__ = [
    "EVIDENCE_SUBJECT_KIND",
    "PRODUCER",
    "REGION_FACT_KEY",
    "UK_ALLOWED_REGIONS",
    "UK_PACK_ID",
    "UK_PACK_VERSION",
    "ResidencyFinding",
    "ResidencyFindingReason",
    "ResidencySweepResult",
    "ResidencySweepStatus",
    "build_residency_sweep_evidence_package",
    "region_fact",
    "sweep_estate_residency",
]
