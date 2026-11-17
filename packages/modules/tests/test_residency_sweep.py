"""Tests for R5-05b sovereignty residency sweeps.

Covers the brief's acceptance criteria:

- a fixture with one in-region and one out-of-region workload produces
  exactly one flagged finding, named and attributable to that specific
  workload;
- a sweep with zero findings still produces a sealed "clean" record, with
  its own explicit status/outcome field -- never indistinguishable from
  "the sweep never ran";
- the sealed evidence record round-trips and verifies offline, and tamper
  is detected -- the same pattern R0-11/R1-17/R3-06's own evidence tests
  already use (``test_transformation_evidence.py``), not a new style.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from cairn_contracts.estate.model import FactStatus, FactValue, Workload
from cairn_kernel.evidence import EvidenceOutput, verify_chain, verify_envelope
from cairn_kernel.testing import FakeEvidenceSigner, FakeEvidenceVerifier
from cairn_modules.sovereignty.residency_sweep import (
    EVIDENCE_SUBJECT_KIND,
    REGION_FACT_KEY,
    UK_ALLOWED_REGIONS,
    ResidencyFindingReason,
    ResidencySweepStatus,
    build_residency_sweep_evidence_package,
    sweep_estate_residency,
)

MOMENT = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"


def _region_fact(value: str | None, *, status: FactStatus = FactStatus.OBSERVED) -> FactValue:
    return FactValue(
        value=value,
        status=status,
        source="test-fixture",
        observed_at=MOMENT if status is FactStatus.OBSERVED else None,
        ingested_at=MOMENT,
        confidence=None,
        mapping_version=None,
        provenance_ref="fixture#0" if status is FactStatus.OBSERVED else "",
    )


def _workload(workload_id: str, name: str, *, facts: dict[str, FactValue]) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name=name,
        environment="prod",
        owner=None,
        business_context=None,
        resource_ids=(),
        dependency_ids=(),
        facts=facts,
        disposition=None,
        disposition_confidence=None,
        model_version="r5-05b-test-v1",
        mapping_version="r5-05b-test-v1",
    )


IN_REGION_WORKLOAD = _workload(
    "workload-in-region",
    "in-region-app",
    facts={REGION_FACT_KEY: _region_fact("europe-west2")},
)

OUT_OF_REGION_WORKLOAD = _workload(
    "workload-out-of-region",
    "out-of-region-app",
    facts={REGION_FACT_KEY: _region_fact("us-east1")},
)

UNKNOWN_REGION_WORKLOAD = _workload(
    "workload-unknown-region",
    "unknown-region-app",
    facts={REGION_FACT_KEY: _region_fact(None, status=FactStatus.UNVERIFIED)},
)

NO_REGION_FACT_WORKLOAD = _workload(
    "workload-no-region-fact",
    "no-region-fact-app",
    facts={},
)


# --- sweep behaviour -----------------------------------------------------------


def test_one_in_region_and_one_out_of_region_produces_exactly_one_finding() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD])

    assert result.status is ResidencySweepStatus.FINDINGS
    assert result.workloads_checked == 2
    assert len(result.findings) == 1

    finding = result.findings[0]
    assert finding.workload_id == OUT_OF_REGION_WORKLOAD.workload_id
    assert finding.workload_name == OUT_OF_REGION_WORKLOAD.name
    assert finding.reason is ResidencyFindingReason.OUT_OF_REGION
    assert finding.declared_region == "us-east1"


def test_all_in_region_produces_zero_findings_but_explicit_clean_status() -> None:
    other_in_region = _workload(
        "workload-in-region-2",
        "in-region-app-2",
        facts={REGION_FACT_KEY: _region_fact("europe-west2")},
    )
    result = sweep_estate_residency([IN_REGION_WORKLOAD, other_in_region])

    assert result.findings == ()
    # The explicit outcome field this result carries -- not merely an
    # empty findings list, which could also mean "nothing was swept".
    assert result.status is ResidencySweepStatus.CLEAN
    assert result.workloads_checked == 2


def test_a_workload_with_no_region_fact_at_all_is_flagged_not_assumed_compliant() -> None:
    result = sweep_estate_residency([NO_REGION_FACT_WORKLOAD])

    assert result.status is ResidencySweepStatus.FINDINGS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.reason is ResidencyFindingReason.REGION_UNKNOWN
    assert finding.declared_region is None


def test_a_workload_with_an_unverified_region_fact_is_flagged() -> None:
    result = sweep_estate_residency([UNKNOWN_REGION_WORKLOAD])

    assert result.status is ResidencySweepStatus.FINDINGS
    assert result.findings[0].reason is ResidencyFindingReason.REGION_UNKNOWN


def test_empty_estate_sweeps_clean_with_zero_workloads_checked() -> None:
    result = sweep_estate_residency([])

    assert result.status is ResidencySweepStatus.CLEAN
    assert result.findings == ()
    assert result.workloads_checked == 0


def test_default_constraint_is_the_adr_016_uk_pack() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD])
    assert result.allowed_regions == tuple(sorted(UK_ALLOWED_REGIONS))
    assert result.pack_id == "uk"


# --- sealing: every sweep run, clean or not, produces a sealed record ---------


def test_a_clean_sweep_still_seals_an_evidence_record_outcome_pass() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD])

    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-clean-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    assert envelope.subject.kind == EVIDENCE_SUBJECT_KIND
    assert envelope.subject.id == PROJECT
    assert envelope.outcome == "PASS"
    assert len(envelope.outputs) == 1
    assert envelope.outputs[0].kind == "residency_sweep_result"

    verification = verify_envelope(envelope, verifier=FakeEvidenceVerifier())
    assert verification.outcome == "PASS"


def test_a_sweep_with_findings_seals_outcome_fail() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD])

    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD],
        package_id="pkg-findings-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    assert envelope.outcome == "FAIL"


def test_sealed_package_records_the_jurisdiction_pack_and_version() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD])
    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    assert envelope.versions["jurisdiction_pack_id"] == result.pack_id
    assert envelope.versions["jurisdiction_pack_version"] == result.pack_version


def test_sealed_package_records_one_input_per_workload_swept() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD])
    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    assert len(envelope.inputs) == 2
    refs = {item.ref for item in envelope.inputs}
    assert refs == {IN_REGION_WORKLOAD.workload_id, OUT_OF_REGION_WORKLOAD.workload_id}
    for item in envelope.inputs:
        assert item.kind == "workload_region"
        assert item.hash


# --- tamper detection, round-trip and offline verification --------------------
# Same pattern R0-11/R1-17/R3-06's own evidence tests already use.


def test_payload_tamper_is_detected() -> None:
    result = sweep_estate_residency([OUT_OF_REGION_WORKLOAD])
    envelope = build_residency_sweep_evidence_package(
        result,
        [OUT_OF_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    tampered = replace(
        envelope,
        outputs=(EvidenceOutput(kind="residency_sweep_result", ref="pkg-1", hash="0" * 64),),
    )

    verification = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert verification.outcome == "FAIL"
    assert not verification.hash_valid
    assert verification.reason == "payload hash does not match the envelope"


def test_signature_tamper_is_detected() -> None:
    result = sweep_estate_residency([IN_REGION_WORKLOAD])
    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    tampered = replace(
        envelope, signature=replace(envelope.signature, value="not-a-real-signature")
    )

    verification = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert verification.outcome == "FAIL"
    assert not verification.signature_valid


def test_package_verifies_independently_offline() -> None:
    """A verifier built with no reference to the signer instance used to
    seal the package -- same key material, independently constructed --
    still verifies it. No network call, no shared in-process object."""
    result = sweep_estate_residency([IN_REGION_WORKLOAD])
    envelope = build_residency_sweep_evidence_package(
        result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    independent_verifier = FakeEvidenceVerifier()
    verification = verify_envelope(envelope, verifier=independent_verifier)

    assert verification.valid
    assert verification.hash_valid and verification.signature_valid and verification.chain_valid


def test_chain_head_across_two_sweep_runs() -> None:
    first_result = sweep_estate_residency([IN_REGION_WORKLOAD])
    first_envelope = build_residency_sweep_evidence_package(
        first_result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )

    second_result = sweep_estate_residency([IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD])
    second_envelope = build_residency_sweep_evidence_package(
        second_result,
        [IN_REGION_WORKLOAD, OUT_OF_REGION_WORKLOAD],
        package_id="pkg-2",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 17, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    assert second_envelope.previous_hash == first_envelope.payload_hash

    chain_result = verify_chain(
        [first_envelope, second_envelope],
        verifier=FakeEvidenceVerifier(),
        expected_head_hash=second_envelope.payload_hash,
    )

    assert chain_result.outcome == "PASS"
    assert chain_result.packages_checked == 2
    assert chain_result.latest_hash == second_envelope.payload_hash


def test_chain_detects_a_tampered_member_across_runs() -> None:
    first_result = sweep_estate_residency([IN_REGION_WORKLOAD])
    first_envelope = build_residency_sweep_evidence_package(
        first_result,
        [IN_REGION_WORKLOAD],
        package_id="pkg-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=MOMENT,
    )
    second_result = sweep_estate_residency([OUT_OF_REGION_WORKLOAD])
    second_envelope = build_residency_sweep_evidence_package(
        second_result,
        [OUT_OF_REGION_WORKLOAD],
        package_id="pkg-2",
        tenant_id=TENANT,
        project_id=PROJECT,
        signer=FakeEvidenceSigner(),
        created_at=datetime(2026, 12, 17, 12, 0, 0, tzinfo=UTC),
        previous_hash=first_envelope.payload_hash,
    )

    tampered_first = replace(
        first_envelope,
        outputs=(EvidenceOutput(kind="residency_sweep_result", ref="pkg-1", hash="0" * 64),),
    )

    chain_result = verify_chain([tampered_first, second_envelope], verifier=FakeEvidenceVerifier())
    assert chain_result.outcome == "FAIL"
    assert not chain_result.hash_valid


# --- no cloud/inventory call from this module itself ---------------------------


def test_no_cloud_or_network_import_in_residency_sweep_module_source() -> None:
    """Construction-proof test, the same AST/source-scan discipline used
    elsewhere in this corpus (R3-06's own
    ``test_no_cloud_or_kms_import_in_evidence_module_source``): this
    module never performs a real cloud inventory call -- it only reads a
    caller-supplied, already-canonical ``Workload`` sequence.
    """
    import ast
    import inspect

    from cairn_modules.sovereignty import residency_sweep as sweep_module

    source = inspect.getsource(sweep_module)
    tree = ast.parse(source)
    banned = {"google", "google.cloud", "boto3", "socket", "urllib", "requests", "http.client"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not (imported & banned), (
        f"unexpected import(s) in residency_sweep.py: {imported & banned}"
    )
