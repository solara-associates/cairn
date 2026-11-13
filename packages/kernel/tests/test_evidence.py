from dataclasses import replace
from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import EvidenceVerificationFailedError, ValidationError
from cairn_kernel.evidence import (
    EvidenceEnvelope,
    EvidenceInput,
    EvidenceOutput,
    EvidenceSignature,
    EvidenceSubject,
    ProvenanceRecord,
    encode_signature,
    envelope_from_dict,
    payload_hash,
    require_verified,
    seal_evidence,
    verify_chain,
    verify_envelope,
)
from cairn_kernel.testing import FakeEvidenceSigner, FakeEvidenceVerifier

CREATED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SUBJECT = EvidenceSubject(kind="assessment", id="33333333-3333-4333-8333-333333333333")


def seal(
    *,
    package_id: str = "pkg-1",
    previous_hash: str | None = None,
    output_hash: str = "a" * 64,
    signer: FakeEvidenceSigner | None = None,
    tenant_id: str = TENANT,
) -> EvidenceEnvelope:
    return seal_evidence(
        signer=signer or FakeEvidenceSigner(),
        package_id=package_id,
        tenant_id=tenant_id,
        project_id=PROJECT,
        subject=SUBJECT,
        created_at=CREATED_AT,
        producer={"name": "assess", "version": "1.0"},
        inputs=[EvidenceInput(kind="estate", ref="estate-1", hash="b" * 64)],
        provenance=[
            ProvenanceRecord(fact_ref="fact-1", source="aws", observed_at=CREATED_AT)
        ],
        versions={"model": "2026.11"},
        assumptions=["read-only estate"],
        policy_decisions=[{"rule": "R-1", "decision": "ALLOW"}],
        model_calls=[{"provider": "fake", "model": "fake-1"}],
        outputs=[EvidenceOutput(kind="finding", ref="finding-1", hash=output_hash)],
        outcome="PASS",
        previous_hash=previous_hash,
    )


def chain(length: int = 3) -> list[EvidenceEnvelope]:
    packages: list[EvidenceEnvelope] = []
    previous: str | None = None
    for index in range(length):
        package = seal(
            package_id=f"pkg-{index + 1}",
            previous_hash=previous,
            output_hash=f"{index + 1:064x}",
        )
        packages.append(package)
        previous = package.payload_hash
    return packages


def test_seal_produces_a_verifiable_signed_envelope() -> None:
    package = seal()
    result = verify_envelope(package, verifier=FakeEvidenceVerifier())
    assert result.outcome == "PASS"
    assert result.valid
    assert result.hash_valid and result.signature_valid and result.chain_valid
    assert result.package_id == "pkg-1"
    assert result.signer_key_id == package.signature.key_id
    assert package.payload_hash == package.compute_payload_hash()
    assert package.to_dict()["payload_hash"] == package.payload_hash


def test_envelope_round_trips_through_a_dict() -> None:
    package = seal()
    restored = envelope_from_dict(package.to_dict())
    assert restored == package
    assert verify_envelope(restored, verifier=FakeEvidenceVerifier()).outcome == "PASS"


def test_payload_hash_is_canonical_across_key_order() -> None:
    assert payload_hash({"b": 1, "a": {"d": 2, "c": 3}}) == payload_hash(
        {"a": {"c": 3, "d": 2}, "b": 1}
    )


def test_payload_tamper_is_detected() -> None:
    package = seal()
    tampered = replace(
        package,
        outputs=(EvidenceOutput(kind="finding", ref="finding-1", hash="0" * 64),),
    )
    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
    assert result.reason == "payload hash does not match the envelope"


def test_payload_tamper_with_recomputed_hash_is_detected_by_signature() -> None:
    package = seal()
    tampered = replace(
        package,
        outputs=(EvidenceOutput(kind="finding", ref="finding-1", hash="0" * 64),),
    )
    tampered = replace(tampered, payload_hash=tampered.compute_payload_hash())
    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert result.hash_valid
    assert not result.signature_valid
    assert result.reason == "signature does not verify"


def test_signature_tamper_is_detected() -> None:
    package = seal()
    tampered = replace(
        package,
        signature=EvidenceSignature(
            key_id=package.signature.key_id,
            algorithm=package.signature.algorithm,
            value=encode_signature(b"not-the-signature"),
        ),
    )
    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert result.hash_valid
    assert not result.signature_valid


def test_previous_hash_tamper_is_detected() -> None:
    packages = chain(2)
    tampered = replace(packages[1], previous_hash="f" * 64)
    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
    assert not result.signature_valid


def test_wrong_key_or_key_id_does_not_verify() -> None:
    package = seal()
    assert (
        verify_envelope(
            package, verifier=FakeEvidenceVerifier(key=b"different-key")
        ).signature_valid
        is False
    )
    assert (
        verify_envelope(
            package, verifier=FakeEvidenceVerifier(key_id="other-key")
        ).signature_valid
        is False
    )


def test_invalid_signature_encoding_fails_without_raising() -> None:
    package = seal()
    tampered = replace(
        package,
        signature=EvidenceSignature(
            key_id=package.signature.key_id,
            algorithm=package.signature.algorithm,
            value="not base64 ***",
        ),
    )
    result = verify_envelope(tampered, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.signature_valid
    assert result.reason is not None


def test_expected_previous_hash_link_is_checked() -> None:
    packages = chain(2)
    verifier = FakeEvidenceVerifier()
    assert (
        verify_envelope(
            packages[1],
            verifier=verifier,
            expected_previous_hash=packages[0].payload_hash,
        ).chain_valid
    )
    assert (
        verify_envelope(
            packages[1],
            verifier=verifier,
            expected_previous_hash=packages[1].payload_hash,
        ).chain_valid
        is False
    )


def test_chain_verification_passes_for_linked_packages() -> None:
    packages = chain(3)
    result = verify_chain(packages, verifier=FakeEvidenceVerifier())
    assert result.outcome == "PASS"
    assert result.valid
    assert result.packages_checked == 3
    assert result.latest_hash == packages[-1].payload_hash
    assert result.reason is None


def test_chain_anchor_mismatch_is_a_failure() -> None:
    packages = chain(3)
    assert (
        verify_chain(
            packages,
            verifier=FakeEvidenceVerifier(),
            expected_head_hash=packages[-1].payload_hash,
        ).outcome
        == "PASS"
    )
    result = verify_chain(
        packages,
        verifier=FakeEvidenceVerifier(),
        expected_head_hash=packages[0].payload_hash,
    )
    assert result.outcome == "FAIL"
    assert not result.chain_valid
    assert result.reason == "latest hash does not match the expected anchor"


def test_chain_detects_a_tampered_member() -> None:
    packages = chain(3)
    middle = packages[1]
    tampered = replace(middle, payload_hash="e" * 64)
    packages[1] = tampered
    result = verify_chain(packages, verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.hash_valid
    assert not result.chain_valid


def test_chain_detects_a_gap() -> None:
    packages = chain(3)
    result = verify_chain([packages[0], packages[2]], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.chain_valid
    assert result.reason is not None


def test_chain_detects_a_fork() -> None:
    packages = chain(3)
    fork = seal(package_id="pkg-fork", previous_hash=packages[1].payload_hash)
    result = verify_chain([*packages, fork], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.chain_valid
    assert "fork" in (result.reason or "")


def test_chain_detects_multiple_roots() -> None:
    packages = chain(2)
    second_root = seal(package_id="pkg-other-root", output_hash="c" * 64)
    result = verify_chain([*packages, second_root], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.chain_valid
    assert result.reason == "expected one chain root, found 2"


def test_chain_detects_mixed_tenants() -> None:
    first = seal(package_id="pkg-1")
    other = seal(
        package_id="pkg-2",
        previous_hash=first.payload_hash,
        tenant_id="44444444-4444-4444-8444-444444444444",
    )
    result = verify_chain([first, other], verifier=FakeEvidenceVerifier())
    assert result.outcome == "FAIL"
    assert not result.chain_valid
    assert result.reason is not None


def test_empty_chain_is_unverified_never_pass() -> None:
    result = verify_chain([], verifier=FakeEvidenceVerifier())
    assert result.outcome == "UNVERIFIED"
    assert not result.valid
    assert result.packages_checked == 0


def test_require_verified_raises_on_failure() -> None:
    verifier = FakeEvidenceVerifier()
    package = seal()
    require_verified(verify_envelope(package, verifier=verifier))
    tampered = replace(package, outcome="FAIL")
    with pytest.raises(EvidenceVerificationFailedError):
        require_verified(verify_envelope(tampered, verifier=verifier))


def test_envelope_rejects_non_sha256_hashes() -> None:
    package = seal()
    with pytest.raises(ValidationError):
        replace(package, payload_hash="not-a-hash")
    with pytest.raises(ValidationError):
        replace(package, previous_hash="xyz")


def test_envelope_requires_signing_identity() -> None:
    package = seal()
    with pytest.raises(ValidationError):
        replace(
            package,
            signature=EvidenceSignature(
                key_id="", algorithm=package.signature.algorithm, value="abc"
            ),
        )


def test_envelope_from_dict_requires_a_signature() -> None:
    data = seal().to_dict()
    data.pop("signature")
    with pytest.raises(ValidationError):
        envelope_from_dict(data)
