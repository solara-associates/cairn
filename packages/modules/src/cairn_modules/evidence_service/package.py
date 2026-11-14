"""R1-17: signed evidence package for an R1-15 assessment run.

Builds an ``EvidenceEnvelope`` for one ``AssessmentRun`` through R0-11's
``seal_evidence`` (hashing/envelope/signing port) -- reused exactly as
built, nothing reimplemented. The envelope's ``subject`` is the
project, not the individual run: a project is assessed repeatedly over
time, and the R1-17 acceptance text asks for "a chain-head test across
multiple evidence packages for the same subject over time," which only
makes sense if the subject outlives a single run.

``build_evidence_package`` then wires the resulting ``payload_hash``
back into R1-16's report via
``cairn_modules.reporting.with_evidence_package_hash`` -- the
placeholder field that story left explicitly named rather than
inventing a reference scheme.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

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

from cairn_modules.assessment import AssessmentRun, RunState
from cairn_modules.reporting import AssessmentReport, render_report, with_evidence_package_hash

EVIDENCE_SUBJECT_KIND = "assessment_project"
PRODUCER = {"name": "cairn-assessment-orchestrator", "version": "r1-17-v1"}


def _stage_input_hash(run: AssessmentRun, stage: str, *, succeeded: bool, completed_at: str | None) -> str:
    """Hash a small, canonical summary of one stage's outcome.

    Not a hash of the stage's full domain output (``Workload``,
    ``CostBaseline``, ... are not all uniformly JSON-serializable) --
    this hashes what every stage outcome has in common: which stage,
    for which run, succeeded or not, and when.
    """
    return payload_hash(
        {"run_id": run.run_id, "stage": stage, "succeeded": succeeded, "completed_at": completed_at}
    )


def _versions(report: AssessmentReport) -> dict[str, str]:
    versions = {
        "control_catalogue": report.versions.control_catalogue_version,
        "price_list": report.versions.price_list_version,
        "mapping_release": report.versions.mapping_release_version,
        "workload_derivation": report.versions.workload_derivation_version,
        "classification": report.versions.classification_version,
    }
    for index, parser_version in enumerate(report.versions.parser_versions):
        versions[f"parser[{index}]"] = parser_version
    return {key: value for key, value in versions.items() if value is not None}


def _outcome(run: AssessmentRun) -> str:
    return "PASS" if run.state is RunState.COMPLETED else "UNVERIFIED"


def build_evidence_package(
    run: AssessmentRun,
    *,
    package_id: str,
    signer: EvidenceSigner,
    created_at: datetime,
    previous_hash: str | None = None,
) -> tuple[EvidenceEnvelope, AssessmentReport]:
    """Build the signed evidence package for ``run`` and the report that
    references it.

    Returns both: the caller (typically the same place that persists
    the report) needs the updated ``AssessmentReport`` with
    ``evidence_package_hash`` filled in, not just the envelope.
    """
    report = render_report(run)

    inputs = tuple(
        EvidenceInput(
            kind="assessment_stage",
            ref=f"{run.run_id}:{outcome.stage}",
            hash=_stage_input_hash(
                run,
                outcome.stage,
                succeeded=outcome.succeeded,
                completed_at=None if outcome.completed_at is None else outcome.completed_at.isoformat(),
            ),
        )
        for outcome in run.outcomes
    )
    provenance = tuple(
        ProvenanceRecord(
            fact_ref=f"stage:{outcome.stage}",
            source="cairn-assessment-orchestrator",
            observed_at=outcome.completed_at,
        )
        for outcome in run.outcomes
    )
    report_hash = hashlib.sha256(report.rendered_text.encode("utf-8")).hexdigest()
    outputs = (EvidenceOutput(kind="assessment_report", ref=run.run_id, hash=report_hash),)

    envelope = seal_evidence(
        signer=signer,
        package_id=package_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        subject=EvidenceSubject(kind=EVIDENCE_SUBJECT_KIND, id=run.project_id),
        created_at=created_at,
        producer=PRODUCER,
        inputs=inputs,
        provenance=provenance,
        versions=_versions(report),
        assumptions=[
            f"horizon_periods={report.tco_assumptions.horizon_periods}",
            f"growth_rate={report.tco_assumptions.growth_rate}",
            f"discount_rate={report.tco_assumptions.discount_rate}",
        ]
        if report.tco_assumptions.horizon_periods is not None
        else [],
        outputs=outputs,
        outcome=_outcome(run),
        previous_hash=previous_hash,
    )

    updated_report = with_evidence_package_hash(report, envelope.payload_hash)
    return envelope, updated_report


__all__ = ["EVIDENCE_SUBJECT_KIND", "PRODUCER", "build_evidence_package"]
