# Evidence-signing key rotation

Status: Evidenced for the evidence-signing key (ADR-008). Proven against
R0-11's evidence kit using its existing fake/test signer and a test trust
store — never a real KMS key, since no cloud account exists for this
repository. In production, the signer named below is backed by the
`cloudkms.signerVerifier` role on `google_kms_crypto_key.evidence_signing`
(`infra/terraform/modules/cairn-evidence/main.tf`); the procedure and the
property being proven (old signatures keep verifying) are identical.

## What this covers

CAIRN signs every evidence package with a KMS-held asymmetric key
(`EC_SIGN_P256_SHA256`), per ADR-008: "The signature covers schema version,
tenant/project, subject, payload hash, previous hash, input versions,
creation time and signer key id. Algorithm and key id are recorded for
agility and rotation." This runbook is the procedure for rotating that key
without invalidating any evidence sealed before the rotation — "signature
agility."

This is **not** a database credential or secret rotation; this key never
leaves KMS (see the comment at the top of `cairn-evidence/main.tf`). Nothing
here is a long-lived exportable secret.

## Why old evidence must keep verifying

The evidence chain (`packages/kernel/src/cairn_kernel/evidence/`) is
append-only and hash-chained. A package's `signature.key_id` field is part
of what gets hashed and signed — it is immutable once sealed. Rotating the
signing key must never require re-signing history; it only changes which
key *new* packages are signed with. Verification therefore needs a trust
store that can hold more than one verification key at once, keyed by
`key_id` — exactly what ADR-008 means by "verification keys are published."

## Rotation procedure

1. **Generate** a new KMS crypto key version (or, outside this repository's
   scope, a wholly new key) with a new, distinct `key_id`. Never reuse an
   existing `key_id` with different signing material — that is exactly the
   ambiguity `key_id` exists to prevent (proven never to pass verification
   in `packages/kernel/tests/test_key_rotation.py::test_rotating_to_the_same_key_id_with_different_material_is_rejected`).
2. **Publish** the new key's verification material alongside the old one.
   Verification must work offline (ADR-008: "verification does not require
   CAIRN to be online") against a trust store holding both keys during the
   overlap window.
3. **Cut over signing**: point the evidence-sealing path
   (`cairn_kernel.evidence.envelope.seal_evidence`'s `signer` argument) at
   the new key. Every package sealed from this moment carries the new
   `key_id`; every package sealed before it still carries the old one and
   is never rewritten.
4. **Verify continuity**: run a chain verification across packages that
   straddle the rotation (pre- and post-rotation) using the trust store from
   step 2, and confirm `PASS` for every package regardless of which key
   signed it.
5. **Retire** the old key only after its retention/compliance window has
   passed and nothing is expected to need it for verification going
   forward. Retiring it before that turns step 4's old packages into
   verification failures — proven as the fail-closed case in
   `test_verification_fails_closed_once_a_retired_key_is_removed_from_the_trust_store`.
6. **Record** the rotation: old key id, new key id, algorithm, rotation
   timestamp, and who authorized it — the same evidentiary standard ADR-008
   requires of everything else CAIRN signs.

## What is tested, and how

`packages/kernel/tests/test_key_rotation.py` runs the rotation procedure's
testable core:

- `test_rotation_preserves_verification_of_pre_rotation_evidence` — seals
  evidence with a signer standing in for the key due for rotation, rotates
  to a new signer/key id, seals more evidence, and proves a
  `RotatingEvidenceVerifier` trust store (`packages/kernel/src/cairn_kernel/testing/fakes.py`)
  holding both key ids verifies every package — old and new — and verifies
  the whole chain across the rotation boundary. This is step 4 above, made
  executable.
- `test_verification_fails_closed_once_a_retired_key_is_removed_from_the_trust_store` —
  proves that once a key is actually removed from the trust store (not
  merely superseded), evidence signed with it fails closed rather than
  silently passing — the negative case for step 5.
- `test_rotating_to_the_same_key_id_with_different_material_is_rejected` —
  proves reusing a `key_id` with different signing material is rejected,
  not silently accepted — the negative case for step 1.

Run them directly:

```bash
uv run pytest packages/kernel/tests/test_key_rotation.py -q
```

They run in CI on every pull request as part of the existing `uv run
pytest` step (`.github/workflows/ci.yml`, job `python`) — no new CI wiring
was needed for this half, since it is an ordinary fast unit test, unlike the
backup/restore dry run which needs a database.

## Known gaps

- This proves rotation against the evidence kit's signer/verifier ports
  (`cairn_kernel.evidence.signing.EvidenceSigner` /
  `EvidenceVerifier`), not against a real Cloud KMS key — `packages/adapters/src/cairn_adapters/evidence_kms`
  is currently an empty adapter package (no KMS-backed implementation
  exists yet to test against). When that adapter is built, its
  rotation should be proven the same way: old signatures still verify
  against a trust store holding both the old and new KMS key versions.
- Customer-held signing keys are out of scope (ADR-008: "not offered until a
  later ADR") and so is their rotation.
