"""Unit coverage for `cairn_adapters.evidence_kms` against a fake KMS
client -- the real client is proven once, locally, by
`tools/ops/kms_signing_proof.py` against the real `solara-cairn-dev` key
(not runnable in CI, which has no GCP credentials). This file proves the
adapter's own logic deterministically: digest construction, DER-signature
pass-through, key_id/algorithm matching, and fail-closed error handling --
using a real EC P-256 key pair generated locally so the fake client's
signature is a genuine signature, not a hardcoded fixture."""

import hashlib

import pytest
from cairn_adapters.evidence_kms import (
    ALGORITHM,
    KmsEvidenceSigner,
    KmsEvidenceVerifier,
    KmsKeyVersion,
)
from cairn_kernel.errors import ProviderUnavailableError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

KEY_VERSION = KmsKeyVersion(
    project_id="cairn-test",
    location="europe-west2",
    key_ring="test-ring",
    key_name="test-key",
    key_version="1",
)


class _SignResponse:
    def __init__(self, signature: bytes) -> None:
        self.signature = signature


class _PublicKeyResponse:
    def __init__(self, pem: str) -> None:
        self.pem = pem


class FakeKmsClient:
    """Stands in for `google.cloud.kms.KeyManagementServiceClient`: a real
    EC P-256 key pair backs it, so signing and the public-key response are
    both genuine cryptographic material, not pre-canned bytes."""

    def __init__(self) -> None:
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self.sign_calls: list[dict[str, object]] = []
        self.get_public_key_calls: list[dict[str, object]] = []
        self.fail_sign = False
        self.fail_get_public_key = False

    def asymmetric_sign(self, request: dict[str, object]) -> _SignResponse:
        self.sign_calls.append(request)
        if self.fail_sign:
            raise RuntimeError("simulated KMS outage")
        digest = request["digest"]["sha256"]  # type: ignore[index]
        signature = self._private_key.sign(digest, ec.ECDSA(Prehashed(hashes.SHA256())))
        return _SignResponse(signature)

    def get_public_key(self, request: dict[str, object]) -> _PublicKeyResponse:
        self.get_public_key_calls.append(request)
        if self.fail_get_public_key:
            raise RuntimeError("simulated KMS outage")
        pem = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return _PublicKeyResponse(pem.decode("ascii"))


def test_sign_sends_the_sha256_digest_of_the_payload_to_the_named_key_version() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)

    payload = b"evidence payload bytes"
    signature = signer.sign(payload)

    assert len(client.sign_calls) == 1
    request = client.sign_calls[0]
    assert request["name"] == KEY_VERSION.resource_name
    assert request["digest"]["sha256"] == hashlib.sha256(payload).digest()
    assert isinstance(signature, bytes) and signature


def test_signer_exposes_key_id_and_algorithm() -> None:
    signer = KmsEvidenceSigner(KEY_VERSION, client=FakeKmsClient())
    assert signer.key_id == KEY_VERSION.resource_name
    assert signer.algorithm == ALGORITHM


def test_sign_failure_is_wrapped_as_provider_unavailable_fail_closed() -> None:
    client = FakeKmsClient()
    client.fail_sign = True
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)

    with pytest.raises(ProviderUnavailableError):
        signer.sign(b"payload")


def test_a_real_signature_verifies_against_the_same_key_version() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)

    payload = b"evidence payload bytes"
    signature = signer.sign(payload)

    assert verifier.verify(
        payload, signature=signature, key_id=signer.key_id, algorithm=signer.algorithm
    )


def test_public_key_is_fetched_once_and_cached() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)
    payload = b"evidence payload bytes"
    signature = signer.sign(payload)

    verifier.verify(payload, signature=signature, key_id=signer.key_id, algorithm=signer.algorithm)
    verifier.verify(payload, signature=signature, key_id=signer.key_id, algorithm=signer.algorithm)

    assert len(client.get_public_key_calls) == 1


def test_a_tampered_payload_does_not_verify() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)

    signature = signer.sign(b"original payload")

    assert not verifier.verify(
        b"tampered payload", signature=signature, key_id=signer.key_id, algorithm=signer.algorithm
    )


def test_a_signature_from_a_different_key_version_does_not_match() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)
    payload = b"evidence payload bytes"
    signature = signer.sign(payload)

    other_key_version = KmsKeyVersion(
        project_id="cairn-test",
        location="europe-west2",
        key_ring="test-ring",
        key_name="test-key",
        key_version="2",
    )
    assert not verifier.verify(
        payload, signature=signature, key_id=other_key_version.resource_name, algorithm=ALGORITHM
    )


def test_an_unrecognised_algorithm_does_not_verify() -> None:
    client = FakeKmsClient()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)
    payload = b"evidence payload bytes"
    signature = signer.sign(payload)

    assert not verifier.verify(
        payload, signature=signature, key_id=signer.key_id, algorithm="FAKE_HMAC_SHA256"
    )


def test_get_public_key_failure_is_wrapped_as_provider_unavailable_fail_closed() -> None:
    client = FakeKmsClient()
    client.fail_get_public_key = True
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)

    with pytest.raises(ProviderUnavailableError):
        verifier.verify(b"payload", signature=b"sig", key_id=KEY_VERSION.resource_name, algorithm=ALGORITHM)
