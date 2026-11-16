"""R3-06: transformation telemetry and evidence record.

Spec S16's R3-06 row: "Detector/pattern versions, inputs, outputs
recorded." This unit extends 726's ``TransformationManifest`` into a
signed, retained evidence record -- it does not replace the manifest,
which remains the one write of record ``cairn_modules.transformation.
runs.TransformationRunRepository`` persists. This module builds one
``EvidenceEnvelope`` per completed transformation run through R0-11's
existing signed-evidence machinery (``cairn_kernel.evidence.
seal_evidence``), reused exactly the way R1-17's ``cairn_modules.
evidence_service.package.build_evidence_package`` already reuses it for
an assessment run -- no new hashing, signing, canonicalization or chain
logic is introduced here, and no cloud credential or KMS call is made
by this module itself. The signer/verifier used is whichever
``EvidenceSigner``/``EvidenceVerifier`` the caller's composition root
already wires in (a ``FakeEvidenceSigner`` in tests; R0-11's
``cairn_adapters.evidence_kms.KmsEvidenceSigner`` in production) --
this module never constructs one and never talks to Cloud KMS, GCP, or
any other provider directly.

Same "verifies independently; tamper detected" discipline R1-17 already
proved for assessment evidence: ``cairn_kernel.evidence.verify_envelope``/
``verify_chain`` work unmodified against the envelope this module builds,
because it is the exact same ``EvidenceEnvelope`` type R1-17 builds, just
with this story's own subject kind, inputs, versions and outputs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from cairn_contracts.transformation import (
    GitRepositoryRef,
    RepositoryRef,
    SourceFile,
    UploadRepositoryRef,
)
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

from cairn_modules.transformation.diff import TransformationDiff
from cairn_modules.transformation.engine import ManifestEntry, TransformationManifest
from cairn_modules.transformation.runs import TransformationRunRecord
from cairn_modules.transformation.validation import ValidationRun

EVIDENCE_SUBJECT_KIND = "transformation_project"
PRODUCER = {"name": "cairn-transformation-engine", "version": "r3-06-v1"}


def _entry_dict(entry: ManifestEntry) -> dict[str, object]:
    """A plain-JSON rendering of one ``ManifestEntry``, for hashing only.

    Deliberately not imported from ``cairn_modules.transformation.runs``
    -- that module's ``_manifest_to_json`` is a private helper scoped to
    its own persistence concern (migration 0008's ``jsonb`` column).
    This is evidence.py's own, independent reading of the same manifest
    shape, used only to compute a stable output hash; a drift between
    the two would be a bug in one of them, not a reason to couple them.
    """

    return {
        "source_file_id": entry.source_file_id,
        "rule_id": entry.rule_id,
        "outcome": entry.outcome.value,
        "reason": entry.reason,
        "edits": [
            {
                "start_byte": edit.start_byte,
                "end_byte": edit.end_byte,
                "start_line": edit.start_line,
                "end_line": edit.end_line,
                "replacement": edit.replacement,
            }
            for edit in entry.edits
        ],
        "detector_version": entry.detector_version,
        "pattern_version": entry.pattern_version,
        "patcher_version": entry.patcher_version,
        "mapping_release_version": entry.mapping_release_version,
    }


def _manifest_payload(manifest: TransformationManifest) -> dict[str, object]:
    return {
        "source_file_ids": list(manifest.source_file_ids),
        "entries": [_entry_dict(entry) for entry in manifest.entries],
    }


def _diff_payload(diff: TransformationDiff) -> dict[str, object]:
    return {
        "run_id": diff.run_id,
        "source_file_ids": list(diff.source_file_ids),
        "files": [
            {
                "source_file_id": file_diff.source_file_id,
                "unified_diff": file_diff.unified_diff,
                "changed": file_diff.changed,
            }
            for file_diff in diff.files
        ],
    }


def _validation_payload(validation: ValidationRun) -> dict[str, object]:
    return {
        "run_id": validation.run_id,
        "approved": validation.approved,
        "results": [
            {"check_id": result.check_id, "passed": result.passed, "reason": result.reason}
            for result in validation.results
        ],
    }


def _repository_ref_payload(ref: RepositoryRef) -> dict[str, object]:
    if isinstance(ref, GitRepositoryRef):
        return {"kind": "GIT", "url": ref.url, "ref": ref.ref}
    if isinstance(ref, UploadRepositoryRef):
        return {"kind": "UPLOAD", "archive_id": ref.archive_id}
    raise ValueError(f"unsupported repository ref: {ref!r}")  # pragma: no cover


def _unique_sorted(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _manifest_versions(manifest: TransformationManifest) -> dict[str, str]:
    """ADR-015's "detector and pattern versions" (plus this manifest's
    own ``patcher_version``/``mapping_release_version`` fields -- the
    same judgement call 726's own handover named explicitly for why
    those two ride alongside the two ADR-015 names by name), recorded as
    the distinct values actually present across the manifest's entries
    -- deduplicated and sorted so a manifest with many entries sharing
    one engine version does not repeat it once per entry. Indexed
    (``detector_version[0]``, ``detector_version[1]``, ...) because a
    single manifest can legitimately cover more than one detector/
    pattern/patcher version (e.g. two rules from different detector
    releases in one run) -- the same multi-value convention R1-17's own
    ``versions[f"parser[{i}]"]`` already uses for a field that is not
    single-valued either.
    """

    versions: dict[str, str] = {}
    for index, version in enumerate(
        _unique_sorted([entry.detector_version for entry in manifest.entries])
    ):
        versions[f"detector_version[{index}]"] = version
    for index, version in enumerate(
        _unique_sorted([entry.pattern_version for entry in manifest.entries])
    ):
        versions[f"pattern_version[{index}]"] = version
    for index, version in enumerate(
        _unique_sorted([entry.patcher_version for entry in manifest.entries])
    ):
        versions[f"patcher_version[{index}]"] = version
    for index, version in enumerate(
        _unique_sorted(
            [
                entry.mapping_release_version
                for entry in manifest.entries
                if entry.mapping_release_version is not None
            ]
        )
    ):
        versions[f"mapping_release_version[{index}]"] = version
    return versions


def _outcome(validation: ValidationRun | None) -> str:
    if validation is None:
        return "PASS"
    return "PASS" if validation.approved else "FAIL"


def build_transformation_evidence_package(
    run: TransformationRunRecord,
    *,
    package_id: str,
    signer: EvidenceSigner,
    created_at: datetime,
    files: Sequence[SourceFile] = (),
    repository_ref: RepositoryRef | None = None,
    diff: TransformationDiff | None = None,
    validation: ValidationRun | None = None,
    previous_hash: str | None = None,
) -> EvidenceEnvelope:
    """Seal one signed evidence record for a completed transformation
    run -- 726's manifest (always available, since ``run`` carries it),
    728's diff and 729's validation outcome when available -- through
    R0-11/R1-17's existing ``seal_evidence``.

    The envelope's ``subject`` is the project, not the individual run --
    the same choice R1-17 made for assessment evidence, for the same
    reason: ``cairn_kernel.evidence.verify_chain``'s own chain-head
    check requires every package in a chain to share one ``subject``
    (``_chain_problem`` rejects a chain whose members disagree on
    tenant/project/subject), and a project is transformed repeatedly
    over time -- each run gets its own ``package_id``/``run_id`` and
    links to the previous run's package via ``previous_hash``, the
    recurring subject that outlives any one run is the project.

    ``files`` is the exact ordered ``SourceFile`` sequence 721's
    ``RepositorySourcePort.fetch`` returned for this run (only ``path``/
    ``content`` are read here, never written); each becomes one
    ``EvidenceInput`` naming the file and a hash of its original content.
    ``repository_ref``, when given, becomes a second kind of input: the
    source ref itself (a Git URL+ref, or an upload archive id) rather
    than the files it resolved to. Both are optional -- a caller that no
    longer has the original ``SourceFile``s can still seal a package
    from the manifest alone ("if available", per the brief) -- but in
    practice at least one of ``files``/``repository_ref`` should be
    given, since an evidence record naming no input at all would not
    meet ADR-015's "inputs ... recorded" requirement; this function does
    not enforce that as a hard precondition (the manifest itself, 726's
    own output, is always one output either way), the completeness test
    for a normally-built package covers it instead.
    """

    subject = EvidenceSubject(kind=EVIDENCE_SUBJECT_KIND, id=run.project_id)

    inputs: list[EvidenceInput] = [
        EvidenceInput(
            kind="source_file",
            ref=source_file.path,
            hash=hashlib.sha256(source_file.content.encode("utf-8")).hexdigest(),
        )
        for source_file in files
    ]
    if repository_ref is not None:
        inputs.append(
            EvidenceInput(
                kind="repository_ref",
                ref=run.run_id,
                hash=payload_hash(_repository_ref_payload(repository_ref)),
            )
        )

    provenance = (
        ProvenanceRecord(
            fact_ref=f"transformation_run:{run.run_id}",
            source="cairn-transformation-engine",
            observed_at=run.created_at,
        ),
    )

    outputs: list[EvidenceOutput] = [
        EvidenceOutput(
            kind="transformation_manifest",
            ref=run.run_id,
            hash=payload_hash(_manifest_payload(run.manifest)),
        )
    ]
    if diff is not None:
        outputs.append(
            EvidenceOutput(
                kind="transformation_diff",
                ref=diff.run_id,
                hash=payload_hash(_diff_payload(diff)),
            )
        )
    if validation is not None:
        outputs.append(
            EvidenceOutput(
                kind="validation_run",
                ref=validation.run_id,
                hash=payload_hash(_validation_payload(validation)),
            )
        )

    return seal_evidence(
        signer=signer,
        package_id=package_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        subject=subject,
        created_at=created_at,
        producer=PRODUCER,
        inputs=tuple(inputs),
        provenance=provenance,
        versions=_manifest_versions(run.manifest),
        outputs=tuple(outputs),
        outcome=_outcome(validation),
        previous_hash=previous_hash,
    )


__all__ = [
    "EVIDENCE_SUBJECT_KIND",
    "PRODUCER",
    "build_transformation_evidence_package",
]
