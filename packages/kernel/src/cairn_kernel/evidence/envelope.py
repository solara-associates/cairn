from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from cairn_kernel.errors import ValidationError
from cairn_kernel.evidence.hashing import payload_hash
from cairn_kernel.evidence.signing import EvidenceSigner, encode_signature
from cairn_kernel.security.canonical import canonical_json

SCHEMA_VERSION = "1.0"
CANONICALIZATION = "RFC8785"
OUTCOMES = frozenset({"PASS", "FAIL", "UNVERIFIED"})
HASH_LENGTH = 64


@dataclass(frozen=True, slots=True)
class EvidenceSubject:
    kind: str
    id: str


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    kind: str
    ref: str
    hash: str


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    fact_ref: str
    source: str
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvidenceOutput:
    kind: str
    ref: str
    hash: str


@dataclass(frozen=True, slots=True)
class EvidenceSignature:
    key_id: str
    algorithm: str
    value: str


def _subject_dict(subject: EvidenceSubject) -> dict[str, str]:
    return {"kind": subject.kind, "id": subject.id}


def _input_dict(item: EvidenceInput) -> dict[str, str]:
    return {"kind": item.kind, "ref": item.ref, "hash": item.hash}


def _provenance_dict(item: ProvenanceRecord) -> dict[str, object]:
    return {
        "fact_ref": item.fact_ref,
        "source": item.source,
        "observed_at": None if item.observed_at is None else item.observed_at.isoformat(),
    }


def _output_dict(item: EvidenceOutput) -> dict[str, str]:
    return {"kind": item.kind, "ref": item.ref, "hash": item.hash}


def _unsigned(
    *,
    schema_version: str,
    package_id: str,
    tenant_id: str,
    project_id: str,
    subject: EvidenceSubject,
    created_at: datetime,
    producer: Mapping[str, str],
    inputs: Sequence[EvidenceInput],
    provenance: Sequence[ProvenanceRecord],
    versions: Mapping[str, str],
    assumptions: Sequence[str],
    policy_decisions: Sequence[Mapping[str, object]],
    model_calls: Sequence[Mapping[str, object]],
    outputs: Sequence[EvidenceOutput],
    outcome: str,
    previous_hash: str | None,
    canonicalization: str,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "package_id": package_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "subject": _subject_dict(subject),
        "created_at": created_at.isoformat(),
        "producer": dict(producer),
        "inputs": [_input_dict(item) for item in inputs],
        "provenance": [_provenance_dict(item) for item in provenance],
        "versions": dict(versions),
        "assumptions": list(assumptions),
        "policy_decisions": [dict(item) for item in policy_decisions],
        "model_calls": [dict(item) for item in model_calls],
        "outputs": [_output_dict(item) for item in outputs],
        "outcome": outcome,
        "previous_hash": previous_hash,
        "canonicalization": canonicalization,
    }


def signing_material(
    *,
    schema_version: str,
    tenant_id: str,
    project_id: str,
    subject: EvidenceSubject,
    payload_hash: str,
    previous_hash: str | None,
    versions: Mapping[str, str],
    created_at: datetime,
    algorithm: str,
    key_id: str,
) -> bytes:
    return canonical_json(
        {
            "schema_version": schema_version,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "subject": _subject_dict(subject),
            "payload_hash": payload_hash,
            "previous_hash": previous_hash,
            "versions": dict(versions),
            "created_at": created_at.isoformat(),
            "algorithm": algorithm,
            "key_id": key_id,
        }
    ).encode("utf-8")


def _is_hash(value: str) -> bool:
    return len(value) == HASH_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    schema_version: str
    package_id: str
    tenant_id: str
    project_id: str
    subject: EvidenceSubject
    created_at: datetime
    producer: Mapping[str, str]
    inputs: tuple[EvidenceInput, ...]
    provenance: tuple[ProvenanceRecord, ...]
    versions: Mapping[str, str]
    assumptions: tuple[str, ...]
    policy_decisions: tuple[Mapping[str, object], ...]
    model_calls: tuple[Mapping[str, object], ...]
    outputs: tuple[EvidenceOutput, ...]
    outcome: str
    previous_hash: str | None
    payload_hash: str
    signature: EvidenceSignature
    canonicalization: str = CANONICALIZATION

    def __post_init__(self) -> None:
        if not self.package_id.strip():
            raise ValidationError("evidence package id is required")
        if self.schema_version != SCHEMA_VERSION:
            raise ValidationError(f"unsupported evidence schema: {self.schema_version}")
        if self.canonicalization != CANONICALIZATION:
            raise ValidationError(
                f"unsupported canonicalization: {self.canonicalization}"
            )
        if self.outcome not in OUTCOMES:
            raise ValidationError(f"unsupported evidence outcome: {self.outcome}")
        if not _is_hash(self.payload_hash):
            raise ValidationError("evidence payload hash is not sha256 hex")
        if self.previous_hash is not None and not _is_hash(self.previous_hash):
            raise ValidationError("evidence previous hash is not sha256 hex")
        if not self.signature.key_id.strip() or not self.signature.algorithm.strip():
            raise ValidationError("evidence signature needs key id and algorithm")

    def unsigned_dict(self) -> dict[str, object]:
        return _unsigned(
            schema_version=self.schema_version,
            package_id=self.package_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            subject=self.subject,
            created_at=self.created_at,
            producer=self.producer,
            inputs=self.inputs,
            provenance=self.provenance,
            versions=self.versions,
            assumptions=self.assumptions,
            policy_decisions=self.policy_decisions,
            model_calls=self.model_calls,
            outputs=self.outputs,
            outcome=self.outcome,
            previous_hash=self.previous_hash,
            canonicalization=self.canonicalization,
        )

    def to_dict(self) -> dict[str, object]:
        data = self.unsigned_dict()
        data["payload_hash"] = self.payload_hash
        data["signature"] = {
            "key_id": self.signature.key_id,
            "algorithm": self.signature.algorithm,
            "value": self.signature.value,
        }
        return data

    def compute_payload_hash(self) -> str:
        return payload_hash(self.unsigned_dict())

    def signing_material(self) -> bytes:
        return signing_material(
            schema_version=self.schema_version,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            subject=self.subject,
            payload_hash=self.payload_hash,
            previous_hash=self.previous_hash,
            versions=self.versions,
            created_at=self.created_at,
            algorithm=self.signature.algorithm,
            key_id=self.signature.key_id,
        )

    def with_signature(self, signature: EvidenceSignature) -> "EvidenceEnvelope":
        return replace(self, signature=signature)


def seal_evidence(
    *,
    signer: EvidenceSigner,
    package_id: str,
    tenant_id: str,
    project_id: str,
    subject: EvidenceSubject,
    created_at: datetime,
    producer: Mapping[str, str],
    inputs: Sequence[EvidenceInput] = (),
    provenance: Sequence[ProvenanceRecord] = (),
    versions: Mapping[str, str] | None = None,
    assumptions: Sequence[str] = (),
    policy_decisions: Sequence[Mapping[str, object]] = (),
    model_calls: Sequence[Mapping[str, object]] = (),
    outputs: Sequence[EvidenceOutput] = (),
    outcome: str = "PASS",
    previous_hash: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    canonicalization: str = CANONICALIZATION,
) -> EvidenceEnvelope:
    resolved_versions: Mapping[str, str] = {} if versions is None else versions
    unsigned = _unsigned(
        schema_version=schema_version,
        package_id=package_id,
        tenant_id=tenant_id,
        project_id=project_id,
        subject=subject,
        created_at=created_at,
        producer=producer,
        inputs=inputs,
        provenance=provenance,
        versions=resolved_versions,
        assumptions=assumptions,
        policy_decisions=policy_decisions,
        model_calls=model_calls,
        outputs=outputs,
        outcome=outcome,
        previous_hash=previous_hash,
        canonicalization=canonicalization,
    )
    digest = payload_hash(unsigned)
    material = signing_material(
        schema_version=schema_version,
        tenant_id=tenant_id,
        project_id=project_id,
        subject=subject,
        payload_hash=digest,
        previous_hash=previous_hash,
        versions=resolved_versions,
        created_at=created_at,
        algorithm=signer.algorithm,
        key_id=signer.key_id,
    )
    signature = EvidenceSignature(
        key_id=signer.key_id,
        algorithm=signer.algorithm,
        value=encode_signature(signer.sign(material)),
    )
    return EvidenceEnvelope(
        schema_version=schema_version,
        package_id=package_id,
        tenant_id=tenant_id,
        project_id=project_id,
        subject=subject,
        created_at=created_at,
        producer=producer,
        inputs=tuple(inputs),
        provenance=tuple(provenance),
        versions=resolved_versions,
        assumptions=tuple(assumptions),
        policy_decisions=tuple(policy_decisions),
        model_calls=tuple(model_calls),
        outputs=tuple(outputs),
        outcome=outcome,
        previous_hash=previous_hash,
        payload_hash=digest,
        signature=signature,
        canonicalization=canonicalization,
    )


def envelope_from_dict(data: Mapping[str, Any]) -> EvidenceEnvelope:
    signature = data.get("signature")
    if not isinstance(signature, Mapping):
        raise ValidationError("evidence signature is required")
    subject = data.get("subject")
    if not isinstance(subject, Mapping):
        raise ValidationError("evidence subject is required")
    try:
        created_at = datetime.fromisoformat(str(data["created_at"]))
        return EvidenceEnvelope(
            schema_version=str(data["schema_version"]),
            package_id=str(data["package_id"]),
            tenant_id=str(data["tenant_id"]),
            project_id=str(data["project_id"]),
            subject=EvidenceSubject(kind=str(subject["kind"]), id=str(subject["id"])),
            created_at=created_at,
            producer=dict(data.get("producer", {})),
            inputs=tuple(
                EvidenceInput(kind=str(item["kind"]), ref=str(item["ref"]), hash=str(item["hash"]))
                for item in data.get("inputs", [])
            ),
            provenance=tuple(
                ProvenanceRecord(
                    fact_ref=str(item["fact_ref"]),
                    source=str(item["source"]),
                    observed_at=None
                    if item.get("observed_at") is None
                    else datetime.fromisoformat(str(item["observed_at"])),
                )
                for item in data.get("provenance", [])
            ),
            versions=dict(data.get("versions", {})),
            assumptions=tuple(str(item) for item in data.get("assumptions", [])),
            policy_decisions=tuple(dict(item) for item in data.get("policy_decisions", [])),
            model_calls=tuple(dict(item) for item in data.get("model_calls", [])),
            outputs=tuple(
                EvidenceOutput(kind=str(item["kind"]), ref=str(item["ref"]), hash=str(item["hash"]))
                for item in data.get("outputs", [])
            ),
            outcome=str(data["outcome"]),
            previous_hash=None
            if data.get("previous_hash") is None
            else str(data["previous_hash"]),
            payload_hash=str(data["payload_hash"]),
            signature=EvidenceSignature(
                key_id=str(signature["key_id"]),
                algorithm=str(signature["algorithm"]),
                value=str(signature["value"]),
            ),
            canonicalization=str(data["canonicalization"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"invalid evidence envelope: {exc}") from exc
