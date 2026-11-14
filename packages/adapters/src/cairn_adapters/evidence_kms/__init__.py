"""Cloud KMS-backed evidence signer/verifier.

Signs through the same ``cairn_kernel.evidence.signing.EvidenceSigner`` /
``EvidenceVerifier`` ports every other signer in this codebase implements
(``cairn_kernel.testing.fakes.FakeEvidenceSigner``, ``apps.api``'s
process-local ``_LocalEvidenceSigner``) -- the evidence-sealing and
verification code in ``cairn_kernel.evidence`` is unmodified; only the key
material and the call move to Cloud KMS. The key never leaves KMS: signing
sends a digest and gets a signature back; the public key used to verify is
fetched once and cached, never the private key.

UK residency (docs/residency/uk-residency-matrix.md, decision 2): the key
this settings object names must live in a ``europe-west2`` key ring --
enforced by Terraform/gcloud when the key is created, not by this adapter,
which only ever addresses the key by its full resource name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from cairn_kernel.errors import ProviderUnavailableError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

ALGORITHM = "GCP_KMS_EC_SIGN_P256_SHA256"


@dataclass(frozen=True, slots=True)
class KmsKeyVersion:
    project_id: str
    location: str
    key_ring: str
    key_name: str
    key_version: str = "1"

    @property
    def resource_name(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/keyRings/{self.key_ring}/cryptoKeys/{self.key_name}"
            f"/cryptoKeyVersions/{self.key_version}"
        )


def _default_client() -> Any:
    from google.cloud import kms

    return kms.KeyManagementServiceClient()


class KmsEvidenceSigner:
    def __init__(self, key_version: KmsKeyVersion, client: Any | None = None) -> None:
        self._key_version = key_version
        self._client = client or _default_client()

    @property
    def key_id(self) -> str:
        return self._key_version.resource_name

    @property
    def algorithm(self) -> str:
        return ALGORITHM

    def sign(self, payload: bytes) -> bytes:
        digest = hashlib.sha256(payload).digest()
        try:
            response = self._client.asymmetric_sign(
                request={
                    "name": self._key_version.resource_name,
                    "digest": {"sha256": digest},
                }
            )
        except Exception as exc:  # fail closed: no local fallback signature
            raise ProviderUnavailableError(f"Cloud KMS sign request failed: {exc}") from exc
        return bytes(response.signature)


class KmsEvidenceVerifier:
    def __init__(self, key_version: KmsKeyVersion, client: Any | None = None) -> None:
        self._key_version = key_version
        self._client = client or _default_client()
        self._public_key: ec.EllipticCurvePublicKey | None = None

    def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        key_id: str,
        algorithm: str,
    ) -> bool:
        if algorithm != ALGORITHM or key_id != self._key_version.resource_name:
            return False
        public_key = self._load_public_key()
        digest = hashlib.sha256(payload).digest()
        try:
            public_key.verify(signature, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
            return True
        except InvalidSignature:
            return False

    def _load_public_key(self) -> ec.EllipticCurvePublicKey:
        if self._public_key is None:
            try:
                response = self._client.get_public_key(
                    request={"name": self._key_version.resource_name}
                )
            except Exception as exc:  # fail closed: no verification without a real key
                raise ProviderUnavailableError(f"Cloud KMS get_public_key failed: {exc}") from exc
            loaded = serialization.load_pem_public_key(response.pem.encode("ascii"))
            if not isinstance(loaded, ec.EllipticCurvePublicKey):
                raise ProviderUnavailableError(
                    f"Cloud KMS key {self._key_version.resource_name} is not an EC public key"
                )
            self._public_key = loaded
        return self._public_key


__all__ = ["ALGORITHM", "KmsEvidenceSigner", "KmsEvidenceVerifier", "KmsKeyVersion"]
