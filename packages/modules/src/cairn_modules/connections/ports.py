"""The outbound port R1-02's connection lifecycle validates against.

This module intentionally does not import any concrete provider adapter.
``cairn_modules`` sits below ``cairn_adapters`` in the layering (see the
``domain-purity`` import-linter contract); the app layer that wires a real
adapter (or, for tests, ``cairn_adapters.provider_core.fake.FakeProviderAdapter``)
is responsible for implementing ``ProviderScopeValidator`` against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScopeCheckResult:
    """The outcome of round-tripping a connection against its provider."""

    read_only: bool
    reachable: bool
    detail: str = ""


class ProviderScopeValidator(Protocol):
    """Confirms a connection's credential grants only a read-only scope and
    round-trips successfully against the provider."""

    def check_scope(
        self, *, provider: str, account_id: str, credential_ref: str
    ) -> ScopeCheckResult: ...


__all__ = ["ProviderScopeValidator", "ScopeCheckResult"]
