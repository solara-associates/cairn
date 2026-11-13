"""R1-05: a small, swappable GCP HTTP port plus rate limiting and retry.

Nothing here imports a GCP SDK. ``GcpHttpClient`` is a ``Protocol`` so tests
(and, eventually, a real client built on ``google-cloud-*`` or plain REST)
can both satisfy it; the contract suite and the rate-limit/retry tests in
this story use a fake implementation.

Retry policy: a response whose ``status_code`` is 429 or a 5xx is retried,
honouring ``Retry-After`` when the fake/real API supplies one, otherwise
backing off exponentially with jitter. After ``max_attempts`` the call
raises ``ProviderUnavailableError`` -- a clean, bounded failure, never a hot
loop and never a hang.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cairn_kernel.errors import ProviderUnavailableError, ValidationError

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class GcpApiResponse:
    """The shape every ``GcpHttpClient`` call returns."""

    status_code: int
    body: Mapping[str, object]
    retry_after_seconds: float | None = None


class GcpHttpClient(Protocol):
    """The outbound port the inventory walker calls through.

    A single ``get`` verb is enough for a read-only inventory walk: list
    calls differ only by path and query parameters.
    """

    def get(
        self, path: str, *, params: Mapping[str, str] | None = None
    ) -> GcpApiResponse: ...


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int = 5
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValidationError("retry max_attempts must be at least 1")
        if self.base_delay_seconds <= 0:
            raise ValidationError("retry base_delay_seconds must be positive")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValidationError(
                "retry max_delay_seconds must be at least base_delay_seconds"
            )


DEFAULT_RETRY_CONFIG = RetryConfig()


class RateLimiter:
    """A leaky-bucket limiter: at most one call per ``1 / max_calls_per_second``.

    ``acquire`` sleeps at most once per call -- it never busy-spins -- and
    the sleep and clock are both injectable so tests run instantly and
    deterministically.
    """

    def __init__(
        self,
        *,
        max_calls_per_second: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls_per_second <= 0:
            raise ValidationError("max_calls_per_second must be positive")
        self._min_interval = 1.0 / max_calls_per_second
        self._sleep = sleep
        self._clock = clock
        self._next_allowed: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._next_allowed is not None and now < self._next_allowed:
            wait = self._next_allowed - now
            self._sleep(wait)
            now = self._next_allowed
        self._next_allowed = now + self._min_interval


def _backoff_delay(
    attempt: int,
    config: RetryConfig,
    retry_after_seconds: float | None,
    rand: Callable[[], float],
) -> float:
    if retry_after_seconds is not None:
        return max(retry_after_seconds, 0.0)
    exponential = min(
        config.base_delay_seconds * (2 ** (attempt - 1)), config.max_delay_seconds
    )
    jitter = exponential * 0.1 * rand()
    return exponential + jitter


def call_with_retry(
    operation: Callable[[], GcpApiResponse],
    *,
    rate_limiter: RateLimiter,
    retry_config: RetryConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> GcpApiResponse:
    """Call ``operation`` behind the rate limiter, retrying on 429/5xx.

    Bounded by ``retry_config.max_attempts``: exhaustion raises
    ``ProviderUnavailableError`` rather than looping forever.
    """

    retry_config = retry_config or DEFAULT_RETRY_CONFIG
    attempt = 0
    while True:
        rate_limiter.acquire()
        response = operation()
        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response
        attempt += 1
        if attempt >= retry_config.max_attempts:
            raise ProviderUnavailableError(
                f"gcp api call did not succeed after {attempt} attempts"
                f" (last status {response.status_code})"
            )
        delay = _backoff_delay(
            attempt, retry_config, response.retry_after_seconds, rand
        )
        sleep(delay)


__all__ = [
    "RETRYABLE_STATUS_CODES",
    "GcpApiResponse",
    "GcpHttpClient",
    "RateLimiter",
    "RetryConfig",
    "call_with_retry",
]
