import hmac
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from cairn_kernel.errors import EvidenceVerificationFailedError
from cairn_kernel.evidence.envelope import EvidenceEnvelope
from cairn_kernel.evidence.signing import EvidenceVerifier, decode_signature
from cairn_kernel.security.canonical import CanonicalJSONError

_UNSET = object()


@dataclass(frozen=True, slots=True)
class EnvelopeVerification:
    package_id: str
    signer_key_id: str
    hash_valid: bool
    signature_valid: bool
    chain_valid: bool
    outcome: str
    verified_at: datetime
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.outcome == "PASS"


@dataclass(frozen=True, slots=True)
class ChainVerification:
    packages_checked: int
    hash_valid: bool
    signature_valid: bool
    chain_valid: bool
    outcome: str
    verified_at: datetime
    latest_hash: str | None = None
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.outcome == "PASS"


def _verify_hash(envelope: EvidenceEnvelope) -> tuple[bool, str | None]:
    try:
        computed = envelope.compute_payload_hash()
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        return False, f"payload cannot be hashed: {exc}"
    if not hmac.compare_digest(computed, envelope.payload_hash):
        return False, "payload hash does not match the envelope"
    return True, None


def _verify_signature(
    envelope: EvidenceEnvelope,
    verifier: EvidenceVerifier,
) -> tuple[bool, str | None]:
    try:
        signature = decode_signature(envelope.signature.value)
    except ValueError as exc:
        return False, str(exc)
    try:
        material = envelope.signing_material()
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        return False, f"signing material cannot be built: {exc}"
    if not verifier.verify(
        material,
        signature=signature,
        key_id=envelope.signature.key_id,
        algorithm=envelope.signature.algorithm,
    ):
        return False, "signature does not verify"
    return True, None


def _first_reason(reasons: list[str]) -> str | None:
    return None if not reasons else "; ".join(reasons)


def verify_envelope(
    envelope: EvidenceEnvelope,
    *,
    verifier: EvidenceVerifier,
    expected_previous_hash: str | None | object = _UNSET,
    verified_at: datetime | None = None,
) -> EnvelopeVerification:
    reasons: list[str] = []
    hash_valid, hash_reason = _verify_hash(envelope)
    if not hash_valid and hash_reason is not None:
        reasons.append(hash_reason)
    signature_valid, signature_reason = _verify_signature(envelope, verifier)
    if not signature_valid and signature_reason is not None:
        reasons.append(signature_reason)
    chain_valid = True
    if (
        expected_previous_hash is not _UNSET
        and envelope.previous_hash != expected_previous_hash
    ):
        chain_valid = False
        reasons.append("previous hash does not match the expected link")
    outcome = (
        "PASS" if hash_valid and signature_valid and chain_valid else "FAIL"
    )
    return EnvelopeVerification(
        package_id=envelope.package_id,
        signer_key_id=envelope.signature.key_id,
        hash_valid=hash_valid,
        signature_valid=signature_valid,
        chain_valid=chain_valid,
        outcome=outcome,
        verified_at=verified_at or datetime.now(UTC),
        reason=_first_reason(reasons),
    )


def _chain_problem(
    packages: tuple[EvidenceEnvelope, ...],
) -> tuple[str | None, str | None]:
    first = packages[0]
    for package in packages[1:]:
        if (
            package.tenant_id != first.tenant_id
            or package.project_id != first.project_id
            or package.subject != first.subject
        ):
            return None, "packages belong to different tenants, projects or subjects"

    by_id: dict[str, EvidenceEnvelope] = {}
    by_hash: dict[str, EvidenceEnvelope] = {}
    for package in packages:
        if package.package_id in by_id:
            return None, f"duplicate package id {package.package_id}"
        by_id[package.package_id] = package
        if package.payload_hash in by_hash:
            return None, f"duplicate payload hash {package.payload_hash}"
        by_hash[package.payload_hash] = package

    roots = [package for package in packages if package.previous_hash is None]
    if len(roots) != 1:
        return None, f"expected one chain root, found {len(roots)}"

    successor: dict[str, EvidenceEnvelope] = {}
    for package in packages:
        if package.previous_hash is None:
            continue
        if package.previous_hash not in by_hash:
            return None, f"{package.package_id} links to a missing package"
        if package.previous_hash in successor:
            return None, f"fork after {package.previous_hash}"
        successor[package.previous_hash] = package

    current = roots[0]
    visited = {current.package_id}
    while current.payload_hash in successor:
        current = successor[current.payload_hash]
        if current.package_id in visited:
            return None, "chain contains a cycle"
        visited.add(current.package_id)
    if len(visited) != len(packages):
        return None, "chain does not include every package"
    return current.payload_hash, None


def verify_chain(
    envelopes: Iterable[EvidenceEnvelope],
    *,
    verifier: EvidenceVerifier,
    expected_head_hash: str | None = None,
    verified_at: datetime | None = None,
) -> ChainVerification:
    packages = tuple(envelopes)
    now = verified_at or datetime.now(UTC)
    if not packages:
        return ChainVerification(
            packages_checked=0,
            hash_valid=False,
            signature_valid=False,
            chain_valid=False,
            outcome="UNVERIFIED",
            verified_at=now,
            reason="no evidence packages",
        )

    reasons: list[str] = []
    hash_valid = True
    signature_valid = True
    for package in packages:
        package_hash_valid, hash_reason = _verify_hash(package)
        if not package_hash_valid:
            hash_valid = False
            reasons.append(f"{package.package_id}: {hash_reason}")
        package_signature_valid, signature_reason = _verify_signature(
            package, verifier
        )
        if not package_signature_valid:
            signature_valid = False
            reasons.append(f"{package.package_id}: {signature_reason}")

    latest_hash, chain_reason = _chain_problem(packages)
    chain_valid = chain_reason is None
    if chain_valid and expected_head_hash is not None and latest_hash != expected_head_hash:
        chain_valid = False
        chain_reason = "latest hash does not match the expected anchor"
    if chain_reason is not None:
        reasons.append(chain_reason)

    outcome = (
        "PASS" if hash_valid and signature_valid and chain_valid else "FAIL"
    )
    return ChainVerification(
        packages_checked=len(packages),
        hash_valid=hash_valid,
        signature_valid=signature_valid,
        chain_valid=chain_valid,
        outcome=outcome,
        verified_at=now,
        latest_hash=latest_hash,
        reason=_first_reason(reasons),
    )


def require_verified(result: EnvelopeVerification | ChainVerification) -> None:
    if result.outcome != "PASS":
        raise EvidenceVerificationFailedError(result.reason or result.outcome)
