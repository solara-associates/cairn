import hashlib
import hmac
from datetime import datetime
from itertools import count

from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.evidence.signing import FAKE_ALGORITHM
from cairn_kernel.security.audit import AuditEntry

DEFAULT_FAKE_EVIDENCE_KEY = b"cairn-fake-evidence-key"
DEFAULT_FAKE_EVIDENCE_KEY_ID = "fake-evidence-key-1"


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FixedIdGenerator:
    def __init__(self, start: int = 1) -> None:
        self._counter = count(start)

    def new_id(self) -> str:
        return f"id-{next(self._counter)}"


class InMemoryUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self.fail_next = False

    def append(self, entry: AuditEntry) -> str:
        if self.fail_next:
            raise AuditUnavailableError("audit sink unavailable")
        self.entries.append(entry)
        return f"audit-{len(self.entries)}"


class FakeEvidenceSigner:
    def __init__(
        self,
        key: bytes = DEFAULT_FAKE_EVIDENCE_KEY,
        key_id: str = DEFAULT_FAKE_EVIDENCE_KEY_ID,
    ) -> None:
        self._key = key
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def algorithm(self) -> str:
        return FAKE_ALGORITHM

    def sign(self, payload: bytes) -> bytes:
        return hmac.new(self._key, payload, hashlib.sha256).digest()


class FakeEvidenceVerifier:
    def __init__(
        self,
        key: bytes = DEFAULT_FAKE_EVIDENCE_KEY,
        key_id: str = DEFAULT_FAKE_EVIDENCE_KEY_ID,
    ) -> None:
        self._key = key
        self._key_id = key_id

    def verify(
        self,
        payload: bytes,
        *,
        signature: bytes,
        key_id: str,
        algorithm: str,
    ) -> bool:
        if algorithm != FAKE_ALGORITHM or key_id != self._key_id:
            return False
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)
