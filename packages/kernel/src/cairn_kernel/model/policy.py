"""Request/response policy enforcement in front of ``ModelPort`` (R5-02a):
a deny-list check, a rate limiter and a circuit breaker. Each is
independently testable and each can block a call before it ever reaches an
adapter -- ``ModelGateway`` (``cairn_kernel.model.gateway``) runs all three,
in this order, before calling ``ModelPort.generate``.

None of these hold a reference to an adapter, a credential or an execution
path; they only ever look at a ``ModelRequest`` and their own prior calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from cairn_kernel.errors import (
    ModelCircuitBreakerOpenError,
    ModelDenyListViolationError,
    ModelRateLimitExceededError,
)
from cairn_kernel.model.ports import ModelRequest


@dataclass(frozen=True, slots=True)
class DenyListPolicy:
    """Blocks a request whose prompt contains any denied term
    (case-insensitive substring match). Deliberately simple: this is a
    policy gate, not a content classifier."""

    terms: frozenset[str] = frozenset()

    def check(self, request: ModelRequest) -> None:
        if not self.terms:
            return
        lowered = request.prompt.lower()
        for term in self.terms:
            if term and term.lower() in lowered:
                raise ModelDenyListViolationError(
                    f"model request prompt matched a denied term: {term!r}"
                )


@dataclass
class RateLimiter:
    """A sliding-window call limiter, scoped per ``tenant_id``.

    ``max_calls`` calls are allowed per ``window``; a call beyond that
    raises before anything is dispatched. State is in-memory and per
    instance -- this is the kernel's policy primitive, not a durable,
    cross-process limiter.
    """

    max_calls: int
    window: timedelta
    _history: dict[str, list[datetime]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if self.window <= timedelta(0):
            raise ValueError("window must be positive")

    def check(self, tenant_id: str, *, now: datetime) -> None:
        history = self._history.setdefault(tenant_id, [])
        cutoff = now - self.window
        while history and history[0] <= cutoff:
            history.pop(0)
        if len(history) >= self.max_calls:
            raise ModelRateLimitExceededError(
                f"tenant {tenant_id!r} exceeded {self.max_calls} model calls per {self.window}"
            )
        history.append(now)

    def exhaust(self, tenant_id: str, *, now: datetime) -> None:
        """Force this limiter's window to its cap for ``tenant_id`` -- the
        cost control loop (R5-02b, ``cairn_kernel.model.control_loop``) calls
        this to THROTTLE a tenant through the rate limiter's own existing
        mechanism, rather than inventing a second blocking path. The next
        ``check`` call within ``window`` of ``now`` raises exactly as if the
        tenant had already made ``max_calls`` calls itself."""

        self._history[tenant_id] = [now] * self.max_calls


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


@dataclass
class CircuitBreaker:
    """Opens after ``failure_threshold`` consecutive failures and stays
    open until ``reset_timeout`` has elapsed, at which point exactly one
    trial call is allowed through (half-open); a success closes it, a
    failure re-opens it immediately for another full ``reset_timeout``.
    """

    failure_threshold: int
    reset_timeout: timedelta
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _opened_at: datetime | None = field(default=None, init=False, repr=False)
    _half_open_trial_in_flight: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.reset_timeout <= timedelta(0):
            raise ValueError("reset_timeout must be positive")

    @property
    def state(self) -> CircuitState:
        return CircuitState.OPEN if self._opened_at is not None else CircuitState.CLOSED

    def check(self, *, now: datetime) -> None:
        if self._opened_at is None:
            return
        if now - self._opened_at < self.reset_timeout:
            raise ModelCircuitBreakerOpenError(
                f"circuit breaker open since {self._opened_at.isoformat()};"
                f" resets after {self.reset_timeout}"
            )
        # Half-open: let exactly one trial call through; record_success /
        # record_failure decides whether it closes or re-opens.
        self._half_open_trial_in_flight = True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
        self._half_open_trial_in_flight = False

    def record_failure(self, *, now: datetime) -> None:
        was_half_open_trial = self._half_open_trial_in_flight
        self._half_open_trial_in_flight = False
        self._consecutive_failures += 1
        if was_half_open_trial or self._consecutive_failures >= self.failure_threshold:
            self._opened_at = now

    def force_open(self, *, now: datetime) -> None:
        """Force the breaker open -- the cost control loop (R5-02b,
        ``cairn_kernel.model.control_loop``) calls this to STOP calls
        through the circuit breaker's own existing mechanism, rather than
        inventing a second blocking path. Equivalent to the breaker having
        just crossed its own ``failure_threshold``: ``check`` raises
        ``ModelCircuitBreakerOpenError`` until ``reset_timeout`` elapses."""

        self._consecutive_failures = max(self._consecutive_failures, self.failure_threshold)
        self._half_open_trial_in_flight = False
        self._opened_at = now


__all__ = ["CircuitBreaker", "CircuitState", "DenyListPolicy", "RateLimiter"]
