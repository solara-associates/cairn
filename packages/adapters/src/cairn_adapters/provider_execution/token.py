"""R4-02a: credential-scoping abstraction (ADR-010 Class C rule 5,
"Execution authorization with scoped, short-lived credentials").

``TokenProvider`` is how a production ``ProviderExecutionPort`` adapter
asks for a credential bound to exactly one revision and operation, uses it
for a single client call, and discards it immediately afterwards -- it
never holds a token beyond that one call, never persists one, and nothing
here reads an environment variable, a config file, or any credential
store. A real implementation would stand in front of whatever workload
identity / short-lived-token-minting infrastructure spec §2.6 sets up --
that infrastructure does not exist yet (it is Allan's job, and the
cloud-gated R4 units 785/786 that depend on it), so no real implementation
exists in this unit, deliberately. ``FakeTokenProvider`` is the only
concrete implementation here, and it is exactly that: fake, in-memory,
never a real secret.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from cairn_kernel.errors import ValidationError

DEFAULT_TOKEN_TTL_SECONDS = 60
MAX_TOKEN_TTL_SECONDS = 900  # 15 minutes: an upper bound on "short-lived"


@dataclass(frozen=True, slots=True)
class TokenRequest:
    """What an adapter asks ``TokenProvider.issue`` for: the exact scope a
    real implementation would mint a workload-identity token against, and
    nothing else -- there is no field here a caller could use to ask for a
    broader or longer-lived credential than one call needs."""

    tenant_id: str
    project_id: str
    revision_id: str
    operation: str
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant id", self.tenant_id),
            ("project id", self.project_id),
            ("revision id", self.revision_id),
            ("operation", self.operation),
        ):
            if not value.strip():
                raise ValidationError(f"token request {name} is required")
        if not 1 <= self.ttl_seconds <= MAX_TOKEN_TTL_SECONDS:
            raise ValidationError(
                f"token request ttl_seconds must be between 1 and {MAX_TOKEN_TTL_SECONDS}"
            )


@dataclass(frozen=True, slots=True)
class ScopedToken:
    """A short-lived, revision-scoped credential handle.

    ``value`` is opaque outside the client it is handed to -- this
    dataclass carries no secret material of its own in this unit (there is
    no real token-minting backend yet), but the shape is the one a real
    token would have: bound to one revision and operation, with an
    explicit expiry a caller can check.
    """

    value: str
    revision_id: str
    operation: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValidationError("scoped token value is required")
        if self.expires_at <= self.issued_at:
            raise ValidationError("scoped token must expire after it is issued")


class TokenProvider(Protocol):
    """Outbound port a production adapter calls to get, and immediately
    give back, a short-lived credential. ``issue`` and ``discard`` are
    always called in pairs by the adapter -- see
    ``cairn_adapters.execution_gcp.adapter.GcpProviderExecutionAdapter.
    apply``/``rollback``, which call ``discard`` from a ``finally`` block
    so a failed client call still releases the token."""

    def issue(self, request: TokenRequest) -> ScopedToken: ...

    def discard(self, token: ScopedToken) -> None: ...


class FakeTokenProvider:
    """Deterministic in-memory ``TokenProvider`` for tests.

    Issues a token whose ``value`` is a monotonic counter -- never a real
    credential, never random, so a test asserting a specific sequence of
    issue/discard calls stays readable. Every issued token is recorded in
    ``issued`` and every discarded one in ``discarded``, so a test can
    assert a token was requested at all, and that it was discarded exactly
    once, without the adapter exposing anything else about the token.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        ttl: timedelta = timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS),
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._issued: list[ScopedToken] = []
        self._discarded: list[ScopedToken] = []
        self._counter = 0

    @property
    def issued(self) -> tuple[ScopedToken, ...]:
        return tuple(self._issued)

    @property
    def discarded(self) -> tuple[ScopedToken, ...]:
        return tuple(self._discarded)

    def issue(self, request: TokenRequest) -> ScopedToken:
        self._counter += 1
        now = self._clock()
        token = ScopedToken(
            value=f"fake-token-{self._counter}",
            revision_id=request.revision_id,
            operation=request.operation,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        self._issued.append(token)
        return token

    def discard(self, token: ScopedToken) -> None:
        self._discarded.append(token)


__all__ = [
    "DEFAULT_TOKEN_TTL_SECONDS",
    "MAX_TOKEN_TTL_SECONDS",
    "FakeTokenProvider",
    "ScopedToken",
    "TokenProvider",
    "TokenRequest",
]
