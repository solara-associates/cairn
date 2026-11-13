import time
from collections.abc import Awaitable, Callable, Mapping
from types import TracebackType
from typing import Any, Self

from opentelemetry import metrics

Scope = dict[str, Any]
Message = dict[str, Any]
App = Callable[
    [Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]],
    Awaitable[None],
]


class RedMetrics:
    """Rate, errors and duration for one service or adapter."""

    def __init__(self, meter: metrics.Meter, *, service: str) -> None:
        if not service.strip():
            raise ValueError("service is required")
        self._service = service
        self._requests = meter.create_counter(
            "cairn.red.requests",
            unit="{request}",
            description="Request rate",
        )
        self._errors = meter.create_counter(
            "cairn.red.errors",
            unit="{error}",
            description="Request error rate",
        )
        self._duration = meter.create_histogram(
            "cairn.red.duration",
            unit="ms",
            description="Request duration",
        )

    def record(
        self,
        *,
        operation: str,
        duration_ms: float,
        failed: bool = False,
        attributes: Mapping[str, str] | None = None,
    ) -> None:
        if not operation.strip():
            raise ValueError("operation is required")
        if duration_ms < 0:
            raise ValueError("duration must not be negative")
        labels = {
            "service": self._service,
            "operation": operation,
            "outcome": "ERROR" if failed else "OK",
        }
        if attributes is not None:
            labels.update(attributes)
        self._requests.add(1, labels)
        self._duration.record(float(duration_ms), labels)
        if failed:
            self._errors.add(1, labels)


class RedTimer:
    def __init__(
        self,
        metrics_recorder: RedMetrics,
        operation: str,
        *,
        attributes: Mapping[str, str] | None = None,
    ) -> None:
        self._metrics = metrics_recorder
        self._operation = operation
        self._attributes = attributes
        self._start: float | None = None

    def __enter__(self) -> Self:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._start is None:
            raise RuntimeError("red timer was not started")
        duration_ms = (time.perf_counter() - self._start) * 1000
        self._metrics.record(
            operation=self._operation,
            duration_ms=duration_ms,
            failed=exc_type is not None,
            attributes=self._attributes,
        )


class RedMiddleware:
    """ASGI middleware that records RED metrics for HTTP requests."""

    def __init__(self, app: App, metrics_recorder: RedMetrics) -> None:
        self._app = app
        self._metrics = metrics_recorder

    async def __call__(
        self,
        scope: Scope,
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        operation = f"{scope.get('method', 'GET')} {scope.get('path', '/')}"
        status = 500

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 500))
            await send(message)

        start = time.perf_counter()
        try:
            await self._app(scope, receive, capture_status)
        except Exception:
            self._metrics.record(
                operation=operation,
                duration_ms=(time.perf_counter() - start) * 1000,
                failed=True,
            )
            raise
        self._metrics.record(
            operation=operation,
            duration_ms=(time.perf_counter() - start) * 1000,
            failed=status >= 500,
        )
