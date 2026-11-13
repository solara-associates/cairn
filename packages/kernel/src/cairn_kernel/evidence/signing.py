import base64
import binascii
from typing import Protocol

from cairn_kernel.hex import Port

FAKE_ALGORITHM = "FAKE_HMAC_SHA256"


def encode_signature(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_signature(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("signature is not valid base64url") from exc


class EvidenceSigner(Port, Protocol):
    @property
    def key_id(self) -> str: ...

    @property
    def algorithm(self) -> str: ...

    def sign(self, payload: bytes) -> bytes: ...


class EvidenceVerifier(Port, Protocol):
    def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        key_id: str,
        algorithm: str,
    ) -> bool: ...
