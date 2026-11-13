"""Proves docs/runbooks/key-rotation.md's procedure for the evidence-signing
key: evidence sealed before a rotation must still verify after it
(signature agility, per ADR-008: "Algorithm and key id are recorded for
agility and rotation" and "Key rotation and verification keys are
published; verification does not require CAIRN to be online.").

This rotates R0-11's evidence kit's existing fake/test signer — never a real
KMS key, since no cloud account exists for this repository.
"""

from datetime import UTC, datetime

from cairn_kernel.evidence import (
    EvidenceInput,
    EvidenceOutput,
    EvidenceSubject,
    ProvenanceRecord,
    seal_evidence,
    verify_chain,
    verify_envelope,
)
from cairn_kernel.testing import (
    FakeEvidenceSigner,
    FakeEvidenceVerifier,
    RotatingEvidenceVerifier,
)

CREATED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SUBJECT = EvidenceSubject(kind="assessment", id="33333333-3333-4333-8333-333333333333")

OLD_KEY = b"cairn-evidence-key-2026-q3"
OLD_KEY_ID = "evidence-signing-2026-q3"
NEW_KEY = b"cairn-evidence-key-2026-q4"
NEW_KEY_ID = "evidence-signing-2026-q4"


def seal(*, signer: FakeEvidenceSigner, package_id: str, previous_hash: str | None, output_hash: str):
    return seal_evidence(
        signer=signer,
        package_id=package_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        subject=SUBJECT,
        created_at=CREATED_AT,
        producer={"name": "assess", "version": "1.0"},
        inputs=[EvidenceInput(kind="estate", ref="estate-1", hash="b" * 64)],
        provenance=[ProvenanceRecord(fact_ref="fact-1", source="aws", observed_at=CREATED_AT)],
        versions={"model": "2026.11"},
        outputs=[EvidenceOutput(kind="finding", ref="finding-1", hash=output_hash)],
        outcome="PASS",
        previous_hash=previous_hash,
    )


def test_rotation_preserves_verification_of_pre_rotation_evidence() -> None:
    """The runbook's dry run: seal evidence with the key due for rotation,
    rotate to a new key, seal more evidence with the new key, and prove a
    verifier that trusts both key ids (the published trust store) still
    verifies everything — old packages included."""
    old_signer = FakeEvidenceSigner(key=OLD_KEY, key_id=OLD_KEY_ID)
    pre_rotation = seal(signer=old_signer, package_id="pkg-1", previous_hash=None, output_hash="a" * 64)

    # Rotation: a new signer with a new key id and (possibly) a new key
    # material replaces the old one for everything sealed from now on. The
    # old envelope is never re-signed — ADR-008 requires the chain to stay
    # append-only and the signature to record the key id it was actually
    # signed with.
    new_signer = FakeEvidenceSigner(key=NEW_KEY, key_id=NEW_KEY_ID)
    post_rotation = seal(
        signer=new_signer,
        package_id="pkg-2",
        previous_hash=pre_rotation.payload_hash,
        output_hash="c" * 64,
    )

    assert pre_rotation.signature.key_id == OLD_KEY_ID
    assert post_rotation.signature.key_id == NEW_KEY_ID

    trust_store = RotatingEvidenceVerifier(
        {
            OLD_KEY_ID: FakeEvidenceVerifier(key=OLD_KEY, key_id=OLD_KEY_ID),
            NEW_KEY_ID: FakeEvidenceVerifier(key=NEW_KEY, key_id=NEW_KEY_ID),
        }
    )

    pre_result = verify_envelope(pre_rotation, verifier=trust_store)
    assert pre_result.outcome == "PASS", pre_result.reason
    assert pre_result.signer_key_id == OLD_KEY_ID

    post_result = verify_envelope(post_rotation, verifier=trust_store)
    assert post_result.outcome == "PASS", post_result.reason
    assert post_result.signer_key_id == NEW_KEY_ID

    chain_result = verify_chain([pre_rotation, post_rotation], verifier=trust_store)
    assert chain_result.outcome == "PASS", chain_result.reason
    assert chain_result.packages_checked == 2


def test_verification_fails_closed_once_a_retired_key_is_removed_from_the_trust_store() -> None:
    """Once a retired key is fully decommissioned (removed from the
    published trust store, not merely superseded), evidence signed with it
    must fail closed rather than silently pass — the chain's gap is a
    verification failure, not a warning (ADR-008)."""
    old_signer = FakeEvidenceSigner(key=OLD_KEY, key_id=OLD_KEY_ID)
    pre_rotation = seal(signer=old_signer, package_id="pkg-1", previous_hash=None, output_hash="a" * 64)

    only_new_key = RotatingEvidenceVerifier(
        {NEW_KEY_ID: FakeEvidenceVerifier(key=NEW_KEY, key_id=NEW_KEY_ID)}
    )
    result = verify_envelope(pre_rotation, verifier=only_new_key)
    assert result.outcome == "FAIL"
    assert not result.signature_valid


def test_rotating_to_the_same_key_id_with_different_material_is_rejected() -> None:
    """A rotation must mint a new key id; reusing a key id with different
    signing material is exactly the ambiguity ADR-008's "algorithm and key
    id are recorded for agility and rotation" exists to prevent."""
    signer_a = FakeEvidenceSigner(key=OLD_KEY, key_id=OLD_KEY_ID)
    package = seal(signer=signer_a, package_id="pkg-1", previous_hash=None, output_hash="a" * 64)

    reused_id_different_key = RotatingEvidenceVerifier(
        {OLD_KEY_ID: FakeEvidenceVerifier(key=NEW_KEY, key_id=OLD_KEY_ID)}
    )
    result = verify_envelope(package, verifier=reused_id_different_key)
    assert result.outcome == "FAIL"
    assert not result.signature_valid
