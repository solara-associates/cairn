"""Real Cloud KMS evidence-signing proof, for the dev cloud foundation.

Proves `cairn_adapters.evidence_kms.{KmsEvidenceSigner,KmsEvidenceVerifier}`
against the real `cairn-dev-evidence-signing` key in `your-dev-project-id`
(europe-west2), not a fake/local signer: seals a real evidence envelope
through `cairn_kernel.evidence.seal_evidence` with the real KMS signer, then
verifies it through the real, unmodified `cairn_kernel.evidence.verify_envelope`
with the real KMS verifier -- the same two functions every other signer in
this codebase (`FakeEvidenceSigner`, `apps.api`'s `_LocalEvidenceSigner`)
seals/verifies through. Also proves a tampered payload is rejected.

This cannot run in CI: it needs real `gcloud` user credentials against a
real GCP project, which CI has no service account for (consistent with
`infra/terraform/README.md`'s own "needs a real GCP project, not something
CI can do" scoping). Run it locally, once, after `gcloud auth login` against
an account with `roles/cloudkms.signerVerifier` on the key:

    uv run python tools/ops/kms_signing_proof.py

Uses the active `gcloud` user's access token directly (via
`google.oauth2.credentials.Credentials`) rather than Application Default
Credentials, because ADC can go stale independently of the CLI's own
session and this script should work whenever `gcloud auth print-access-token`
does.
"""

from __future__ import annotations

import dataclasses
import subprocess
from datetime import UTC, datetime

from cairn_adapters.evidence_kms import KmsEvidenceSigner, KmsEvidenceVerifier, KmsKeyVersion
from cairn_kernel.evidence import (
    EvidenceSubject,
    require_verified,
    seal_evidence,
    verify_envelope,
)
from google.cloud import kms
from google.oauth2.credentials import Credentials

# Edit project_id to the real GCP project before running this locally.
KEY_VERSION = KmsKeyVersion(
    project_id="your-dev-project-id",
    location="europe-west2",
    key_ring="cairn-dev-evidence",
    key_name="cairn-dev-evidence-signing",
    key_version="1",
)


def log(message: str) -> None:
    print(f"[kms-signing-proof] {message}", flush=True)


def _kms_client() -> kms.KeyManagementServiceClient:
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    return kms.KeyManagementServiceClient(credentials=Credentials(token))


def main() -> None:
    client = _kms_client()
    signer = KmsEvidenceSigner(KEY_VERSION, client=client)
    verifier = KmsEvidenceVerifier(KEY_VERSION, client=client)

    log(f"signing with real key {signer.key_id}")
    envelope = seal_evidence(
        signer=signer,
        package_id="kms-signing-proof-1",
        tenant_id="00000000-0000-0000-0000-000000000000",
        project_id="00000000-0000-0000-0000-000000000000",
        subject=EvidenceSubject(kind="proof", id="kms-signing-proof"),
        created_at=datetime.now(UTC),
        producer={"name": "kms_signing_proof.py"},
    )
    log(f"sealed envelope, signature algorithm={envelope.signature.algorithm}")

    result = verify_envelope(envelope, verifier=verifier)
    log(f"verify_envelope outcome={result.outcome} reason={result.reason}")
    require_verified(result)
    log("PASS: a real KMS-signed envelope verifies through cairn_kernel.evidence.verify_envelope")

    tampered = dataclasses.replace(envelope, payload_hash="0" * 64)
    tampered_result = verify_envelope(tampered, verifier=verifier)
    assert tampered_result.outcome == "FAIL", "a tampered envelope must not verify"
    log("PASS: a tampered envelope is correctly rejected")


if __name__ == "__main__":
    main()
