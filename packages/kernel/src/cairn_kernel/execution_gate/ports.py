"""The execution-gate adapter port and its no-production-adapter guard
(ADR-010, R1-22).

Every Class C mutation dispatches through ``ExecutionAdapterPort``. In R1
exactly one concrete implementation may exist — the deterministic test
adapter (``cairn_kernel.execution_gate.deterministic_adapter``) — and ADR-010
requires that no code path, config flag or environment variable can swap in
a production adapter instead. ``Protocol`` gives structural typing, which a
type checker cannot use to forbid a look-alike class; ``require_deterministic_
test_adapter`` is the runtime guard that makes the prohibition real: it is
called unconditionally by every gate, reads no configuration, and fails
closed against anything that does not self-identify with the one allowed
``adapter_kind``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from cairn_kernel.errors import ConfigurationError

#: The only adapter kind the gate will ever dispatch to before R4 (ADR-010:
#: "The test adapter cannot be substituted with a production provider
#: adapter"). There is no registry or mapping from other strings to this
#: value, and nothing here reads an environment variable or config file —
#: the guard below is a single literal comparison.
DETERMINISTIC_TEST_ADAPTER_KIND = "DETERMINISTIC_TEST"


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    """What the gate hands to the adapter: a synthetic operation name and a
    plain-data payload. No connection details, no credentials — those are
    never constructed by anything in this package."""

    operation: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AdapterResult:
    status: str
    detail: Mapping[str, object]


class ExecutionAdapterPort(Protocol):
    """Outbound port every mutation dispatch goes through. Interfaces call
    the gate; the gate calls this port; nothing calls a concrete adapter
    directly (ADR-010: "No Class C operation may execute outside the shared
    execution gate")."""

    adapter_kind: str

    def execute(self, request: AdapterRequest) -> AdapterResult: ...


def require_deterministic_test_adapter(adapter: ExecutionAdapterPort) -> None:
    """Fail closed unless ``adapter`` self-identifies as the R1 deterministic
    test adapter.

    Structural typing means anything exposing an ``execute(request)`` method
    satisfies ``ExecutionAdapterPort`` at the type-checker level — a
    look-alike "production" adapter would type-check as this port. This is
    the runtime check every gate constructor calls unconditionally, so that
    type-level satisfaction is never enough to reach a real effect.
    """

    kind = getattr(adapter, "adapter_kind", None)
    if kind != DETERMINISTIC_TEST_ADAPTER_KIND:
        raise ConfigurationError(
            "the execution gate will only dispatch to the deterministic test"
            f" adapter (adapter_kind={DETERMINISTIC_TEST_ADAPTER_KIND!r});"
            f" got adapter_kind={kind!r}"
        )


__all__ = [
    "DETERMINISTIC_TEST_ADAPTER_KIND",
    "AdapterRequest",
    "AdapterResult",
    "ExecutionAdapterPort",
    "require_deterministic_test_adapter",
]
