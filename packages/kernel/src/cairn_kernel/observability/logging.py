import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

REQUIRED_LOG_FIELDS = (
    "correlation_id",
    "tenant_id",
    "project_id",
    "operation_id",
)


def hash_identifier(value: str, *, salt: str = "") -> str:
    return hashlib.sha256(f"{salt}{value}".encode()).hexdigest()


def log_context(
    *,
    correlation_id: str,
    tenant_id: str,
    project_id: str | None = None,
    operation_id: str | None = None,
    hash_tenant: bool = False,
    salt: str = "",
) -> dict[str, str | None]:
    return {
        "correlation_id": correlation_id,
        "tenant_id": hash_identifier(tenant_id, salt=salt) if hash_tenant else tenant_id,
        "project_id": project_id,
        "operation_id": operation_id,
    }


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = getattr(record, "context", {})
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if isinstance(context, Mapping):
            payload.update(context)
        for field in REQUIRED_LOG_FIELDS:
            payload.setdefault(field, None)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


class StructuredLogger:
    def __init__(
        self,
        name: str = "cairn",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(name)

    def emit(
        self,
        event: str,
        *,
        context: Mapping[str, object] | None = None,
        level: int = logging.INFO,
    ) -> None:
        self._logger.log(level, event, extra={"context": dict(context or {})})
