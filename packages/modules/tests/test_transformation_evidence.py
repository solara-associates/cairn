"""Tests for R3-06 transformation telemetry and evidence record.

Covers the acceptance criterion: "Detector/pattern versions, inputs,
outputs recorded" plus the same "verifies independently; tamper
detected" discipline R1-17 already proved for assessment evidence --
reused here through R0-11's existing ``cairn_kernel.evidence`` machinery
unmodified (``seal_evidence``/``verify_envelope``/``verify_chain``).

- round-trip test: a sealed package verifies with a fresh, independently
  constructed verifier that shares no in-process object with the signer;
- tamper test: mutating one field (an output hash) breaks verification,
  the exact pattern R0-11/R1-17 used;
- completeness test: every field spec S16's R3-06 acceptance text names
  (detector version, pattern version, inputs, outputs) is present on the
  sealed envelope;
- chain-head test: two evidence packages for two runs of the same
  transformation, linked and verified as one chain.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from cairn_contracts.transformation import GitRepositoryRef, SourceFile, SourceLanguage
from cairn_kernel.evidence import EvidenceOutput, verify_chain, verify_envelope
from cairn_kernel.testing import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.evidence import (
    EVIDENCE_SUBJECT_KIND,
    build_transformation_evidence_package,
)
from cairn_modules.transformation.runs import TransformationRunRecord
from cairn_modules.transformation.validation import ValidationResult, ValidationRun

MOMENT = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"

SOURCE_FILE = SourceFile(
    path="s3.tf",
    content='resource "aws_s3_bucket" "x" {\n  acl = "public-read"\n}\n',
    language=SourceLanguage.TERRAFORM,
)

APPLIED_ENTRY = ManifestEntry(
    source_file_id="s3.tf",
    rule_id="tf-s3-bucket-inline-acl-deprecated",
    outcome=ManifestOutcome.APPLIED,
    reason=None,
    edits=(
        ManifestEdit(
            start_byte=33,
            end_byte=52,
            start_line=2,
            end_line=2,
            replacement='acl = "private"',
        ),
    ),
    detector_version="cairn-detector/0.1.0",
    pattern_version="cairn-hcl-parser/0.1.0",
    patcher_version="cairn-transform-patcher/0.1.0",
    mapping_release_version=None,
)

SKIPPED_ENTRY = ManifestEntry(
    source_file_id="s3.tf",
    rule_id="tf-s3-bucket-versioning-recommended",
    outcome=ManifestOutcome.SKIPPED,
    reason="already compliant",
    edits=(),
    detector_version="cairn-detector/0.1.0",
    pattern_version="cairn-hcl-parser/0.1.0",
    patcher_version="cairn-transform-patcher/0.1.0",
    mapping_release_version=None,
)

MANIFEST = TransformationManifest(
    source_file_ids=("s3.tf",),
    entries=(APPLIED_ENTRY, SKIPPED_ENTRY),
)

REPOSITORY_REF = GitRepositoryRef(url="https://example.test/repo.git", ref="main")


def _run(run_id: str, *, run_number: int = 1) -> TransformationRunRecord:
    return TransformationRunRecord(
        run_id=run_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        run_number=run_number,
        manifest=MANIFEST,
        created_by="user-1",
        created_at=MOMENT,
    )


def _diff(run_id: str):
    return render_transformation_diff(run_id=run_id, files=[SOURCE_FILE], manifest=MANIFEST)


def _validation(run_id: str) -> ValidationRun:
    return ValidationRun(
        run_id=run_id,
        results=(ValidationResult(check_id="static-reparse", passed=True),),
    )


# --- sealing -----------------------------------------------------------------


def test_build_transformation_evidence_package_seals_a_verifiable_package() -> None:
    run = _run("run-1")
    diff = _diff("run-1")
    validation = _validation("run-1")

    envelope = build_transformation_evidence_package(
        run,
        package_id="pkg-1",
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
        files=[SOURCE_FILE],
        repository_ref=REPOSITORY_REF,
        diff=diff,
        validation=validation,
    )

    assert envelope.subject.kind == EVIDENCE_SUBJECT_KIND
    assert envelope.subject.id == PROJECT
    assert envelope.outcome == "PASS"

    result = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert result.outcome == "PASS"


def test_a_failing_validation_run_seals_as_fail_not_pass() -> None:
    run = _run("run-1")
    validation = ValidationRun(
        run_id="run-1",
        results=(ValidationResult(check_id="static-reparse", passed=False, reason="syntax broke"),),
    )

    envelope = build_transformation_evidence_package(
        run,
        package_id="pkg-1",
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
        validation=validation,
    )

    assert envelope.outcome == "FAIL"


def test_diff_and_validation_are_optional_manifest_alone_still_seals() -> None:
    run = _run("run-1")

    envelope = build_transformation_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    assert envelope.outcome == "PASS"
    assert len(envelope.outputs) == 1
    assert envelope.outputs[0].kind == "transformation_manifest"

    result = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert result.outcome == "PASS"


# --- completeness: every R3-06 acceptance field is present -------------------


def test_completeness_every_r3_06_named_field_is_present() -> None:
    run = _run("run-1")
    diff = _diff("run-1")
    validation = _validation("run-1")

    envelope = build_transformation_evidence_package(
        run,
        package_id="pkg-1",
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
        files=[SOURCE_FILE],
        repository_ref=REPOSITORY_REF,
        diff=diff,
        validation=validation,
    )

    # Detector version: present and matches the manifest's own entries.
    detector_versions = {value for key, value in envelope.versions.items() if key.startswith("detector_version")}
    assert detector_versions == {"cairn-detector/0.1.0"}

    # Pattern version: present (ADR-015's own name, recorded from the
    # parser/grammar version per 726's judgement call).
    pattern_versions = {value for key, value in envelope.versions.items() if key.startswith("pattern_version")}
    assert pattern_versions == {"cairn-hcl-parser/0.1.0"}

    # Patcher version recorded too (not named in ADR-015's own sentence,
    # but the same kind of fact -- present alongside the two it does name).
    patcher_versions = {value for key, value in envelope.versions.items() if key.startswith("patcher_version")}
    assert patcher_versions == {"cairn-transform-patcher/0.1.0"}

    # Inputs: every given source file, plus the repository ref, each
    # with a non-empty hash -- "every input ... recorded".
    assert len(envelope.inputs) == 2
    input_kinds = {item.kind for item in envelope.inputs}
    assert input_kinds == {"source_file", "repository_ref"}
    for item in envelope.inputs:
        assert item.hash
        assert item.ref

    # Outputs: the manifest, the diff and the validation run -- "every
    # output ... recorded".
    output_kinds = {item.kind for item in envelope.outputs}
    assert output_kinds == {"transformation_manifest", "transformation_diff", "validation_run"}
    for item in envelope.outputs:
        assert item.hash


def test_completeness_with_no_mapping_release_version_records_none() -> None:
    # Confirmed, not assumed: today's corpus never calls R2-01's mapping
    # resolver (726/728/729's handovers), so no mapping_release_version[*]
    # key is ever added -- never fabricated as a placeholder.
    run = _run("run-1")
    envelope = build_transformation_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )
    assert not any(key.startswith("mapping_release_version") for key in envelope.versions)


# --- tamper detection, reusing R0-11's exact pattern --------------------------


def test_payload_tamper_is_detected() -> None:
    run = _run("run-1")
    envelope = build_transformation_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    tampered = replace(
        envelope,
        outputs=(EvidenceOutput(kind="transformation_manifest", ref=run.run_id, hash="0" * 64),),
    )

    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
    assert result.reason == "payload hash does not match the envelope"


def test_signature_tamper_is_detected() -> None:
    run = _run("run-1")
    envelope = build_transformation_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    tampered = replace(envelope, signature=replace(envelope.signature, value="not-a-real-signature"))

    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.signature_valid


# --- independent, offline verification ----------------------------------------


def test_package_verifies_independently_offline() -> None:
    """A verifier built with no reference to the signer instance used to
    seal the package -- same key material, independently constructed --
    still verifies it. No network call, no shared in-process object."""
    run = _run("run-1")
    envelope = build_transformation_evidence_package(
        run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    independent_verifier = FakeEvidenceVerifier()
    result = verify_envelope(envelope, verifier=independent_verifier)

    assert result.valid
    assert result.hash_valid and result.signature_valid and result.chain_valid


# --- chain-head across multiple transformation runs --------------------------


def test_chain_head_across_two_runs_of_the_same_transformation() -> None:
    first_run = _run("run-1", run_number=1)
    first_envelope = build_transformation_evidence_package(
        first_run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )

    second_run = _run("run-2", run_number=2)
    second_envelope = build_transformation_evidence_package(
        second_run,
        package_id="pkg-2",
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 16, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    assert second_envelope.previous_hash == first_envelope.payload_hash

    result = verify_chain(
        [first_envelope, second_envelope],
        verifier=FakeEvidenceVerifier(),
        expected_head_hash=second_envelope.payload_hash,
    )

    assert result.outcome == "PASS"
    assert result.packages_checked == 2
    assert result.latest_hash == second_envelope.payload_hash


def test_chain_detects_a_tampered_member_across_runs() -> None:
    first_run = _run("run-1", run_number=1)
    first_envelope = build_transformation_evidence_package(
        first_run, package_id="pkg-1", signer=FakeEvidenceSigner(), created_at=MOMENT
    )
    second_run = _run("run-2", run_number=2)
    second_envelope = build_transformation_evidence_package(
        second_run,
        package_id="pkg-2",
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 16, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    tampered_first = replace(
        first_envelope,
        outputs=(EvidenceOutput(kind="transformation_manifest", ref=first_run.run_id, hash="0" * 64),),
    )

    result = verify_chain([tampered_first, second_envelope], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid


# --- no cloud/KMS call from this module itself --------------------------------


def test_no_cloud_or_kms_import_in_evidence_module_source() -> None:
    """Construction-proof test, the same AST/source-scan discipline used
    elsewhere in this corpus (``cairn_adapters.transform_core``'s
    ``no_network_imports_in_cli_source``): this module reuses R0-11's
    signer/verifier *ports* only -- it never imports Cloud KMS, a cloud
    SDK, or any networking module itself, since the actual signing call
    belongs to whichever adapter (fake or ``cairn_adapters.evidence_kms``)
    the caller already wired in, not to this module.
    """
    import ast
    import inspect

    from cairn_modules.transformation import evidence as evidence_module

    source = inspect.getsource(evidence_module)
    tree = ast.parse(source)
    banned = {"google", "google.cloud", "boto3", "socket", "urllib", "requests", "http.client"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not (imported & banned), f"unexpected import(s) in evidence.py: {imported & banned}"


@pytest.mark.parametrize("run_number", [1, 2, 3])
def test_run_number_does_not_affect_sealing(run_number: int) -> None:
    run = _run(f"run-{run_number}", run_number=run_number)
    envelope = build_transformation_evidence_package(
        run, package_id=f"pkg-{run_number}", signer=FakeEvidenceSigner(), created_at=MOMENT
    )
    assert envelope.outcome == "PASS"
