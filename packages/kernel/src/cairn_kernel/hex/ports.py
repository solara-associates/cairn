import uuid
from datetime import UTC, datetime
from typing import Protocol

from cairn_kernel.hex.primitives import Port


class Clock(Port, Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Port, Protocol):
    def new_id(self) -> str: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    def new_id(self) -> str:
        return str(uuid.uuid4())
