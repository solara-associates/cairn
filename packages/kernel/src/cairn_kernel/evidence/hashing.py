import hashlib

from cairn_kernel.security.canonical import canonical_json


def canonical_bytes(payload: object) -> bytes:
    return canonical_json(payload).encode("utf-8")


def payload_hash(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
