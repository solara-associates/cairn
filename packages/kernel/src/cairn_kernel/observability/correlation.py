import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

CORRELATION_HEADER = "x-correlation-id"

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cairn_correlation_id", default=None
)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def correlation_from_header(value: str | None) -> str:
    if value is None or not value.strip():
        return new_correlation_id()
    return value.strip()


def current_correlation_id() -> str | None:
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str) -> Iterator[str]:
    token = _correlation_id.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id.reset(token)
