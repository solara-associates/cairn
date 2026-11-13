"""R1-05: rate limiting and retry for the GCP inventory adapter's HTTP port.

These are unit tests against ``cairn_adapters.provider_gcp.client`` directly
-- no inventory walk involved -- so the backoff and exhaustion behaviour is
exercised in isolation. Sleep and randomness are injected; nothing here
sleeps for real, so the "verified" claim in the R1-05 acceptance criterion
is about call counts and delay shape, not wall-clock timing.
"""

from __future__ import annotations

import pytest
from cairn_adapters.provider_gcp.client import (
    GcpApiResponse,
    RateLimiter,
    RetryConfig,
    call_with_retry,
)
from cairn_kernel.errors import ProviderUnavailableError, ValidationError

OK = GcpApiResponse(status_code=200, body={"ok": True})
RATE_LIMITED = GcpApiResponse(status_code=429, body={})
RATE_LIMITED_WITH_RETRY_AFTER = GcpApiResponse(
    status_code=429, body={}, retry_after_seconds=2.5
)
SERVER_ERROR = GcpApiResponse(status_code=503, body={})


def test_rate_limiter_spaces_calls_with_one_bounded_sleep_per_acquire() -> None:
    clock_value = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return clock_value[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock_value[0] += seconds

    limiter = RateLimiter(max_calls_per_second=2.0, sleep=sleep, clock=clock)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    # First acquire never waits; the next two each wait once for the
    # remainder of the 0.5s interval -- never a busy loop of many tiny
    # sleeps.
    assert len(sleeps) == 2
    assert sleeps == pytest.approx([0.5, 0.5])


def test_rate_limiter_does_not_wait_when_calls_are_already_spaced_out() -> None:
    clock_value = [0.0]
    sleeps: list[float] = []

    limiter = RateLimiter(
        max_calls_per_second=10.0,
        sleep=lambda seconds: sleeps.append(seconds),
        clock=lambda: clock_value[0],
    )

    limiter.acquire()
    clock_value[0] += 5.0  # plenty of real time has passed
    limiter.acquire()

    assert sleeps == []


def test_rate_limiter_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValidationError):
        RateLimiter(max_calls_per_second=0)
    with pytest.raises(ValidationError):
        RateLimiter(max_calls_per_second=-1)


def _no_wait_limiter() -> RateLimiter:
    return RateLimiter(max_calls_per_second=1_000, sleep=lambda seconds: None)


def test_call_with_retry_backs_off_on_429_then_succeeds() -> None:
    responses = [RATE_LIMITED, RATE_LIMITED, OK]
    calls: list[None] = []
    delays: list[float] = []

    def operation() -> GcpApiResponse:
        calls.append(None)
        return responses[len(calls) - 1]

    result = call_with_retry(
        operation,
        rate_limiter=_no_wait_limiter(),
        retry_config=RetryConfig(max_attempts=5, base_delay_seconds=0.1),
        sleep=delays.append,
        rand=lambda: 0.0,
    )

    assert result is OK
    assert len(calls) == 3
    # Exponential backoff: second attempt's delay is roughly double the
    # first's -- confirms backoff is happening, not a fixed/no-op wait.
    assert len(delays) == 2
    assert delays[0] == pytest.approx(0.1)
    assert delays[1] == pytest.approx(0.2)


def test_call_with_retry_honours_retry_after_over_backoff() -> None:
    responses = [RATE_LIMITED_WITH_RETRY_AFTER, OK]
    calls: list[None] = []
    delays: list[float] = []

    def operation() -> GcpApiResponse:
        calls.append(None)
        return responses[len(calls) - 1]

    call_with_retry(
        operation,
        rate_limiter=_no_wait_limiter(),
        retry_config=RetryConfig(base_delay_seconds=5.0),
        sleep=delays.append,
        rand=lambda: 0.0,
    )

    assert delays == [2.5]


def test_call_with_retry_retries_server_errors_too() -> None:
    responses = [SERVER_ERROR, OK]
    calls: list[None] = []

    def operation() -> GcpApiResponse:
        calls.append(None)
        return responses[len(calls) - 1]

    result = call_with_retry(
        operation,
        rate_limiter=_no_wait_limiter(),
        retry_config=RetryConfig(base_delay_seconds=0.01),
        sleep=lambda seconds: None,
        rand=lambda: 0.0,
    )

    assert result is OK
    assert len(calls) == 2


def test_call_with_retry_exhausts_and_raises_cleanly_without_hanging() -> None:
    calls: list[None] = []
    sleeps: list[float] = []

    def always_rate_limited() -> GcpApiResponse:
        calls.append(None)
        return RATE_LIMITED

    with pytest.raises(ProviderUnavailableError):
        call_with_retry(
            always_rate_limited,
            rate_limiter=_no_wait_limiter(),
            retry_config=RetryConfig(max_attempts=4, base_delay_seconds=0.01),
            sleep=sleeps.append,
            rand=lambda: 0.0,
        )

    # Bounded: exactly max_attempts calls were made and the function
    # returned (raised) instead of looping forever.
    assert len(calls) == 4
    assert len(sleeps) == 3


def test_retry_config_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        RetryConfig(max_attempts=0)
    with pytest.raises(ValidationError):
        RetryConfig(base_delay_seconds=0)
    with pytest.raises(ValidationError):
        RetryConfig(base_delay_seconds=1.0, max_delay_seconds=0.5)
