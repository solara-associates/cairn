from datetime import datetime
from itertools import count

from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.security.audit import AuditEntry


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
