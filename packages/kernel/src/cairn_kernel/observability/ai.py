import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cairn_kernel.errors import ValidationError
from cairn_kernel.observability.logging import StructuredLogger, log_context

INPUT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AiCallRecord:
    provider: str
    model: str
    input_hash: str
    schema_valid: bool
    outcome: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    correlation_id: str
    tenant_id: str
    project_id: str | None = None
    agent_run_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("outcome", self.outcome),
            ("correlation id", self.correlation_id),
            ("tenant id", self.tenant_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"AI call {field} is required")
        if not isinstance(self.input_hash, str) or not INPUT_HASH_PATTERN.match(
            self.input_hash
        ):
            raise ValidationError("AI call input hash is not sha256 hex")
        if not isinstance(self.schema_valid, bool):
            raise ValidationError("AI call schema validity must be a boolean")
        for field, value in (
            ("latency", self.latency_ms),
            ("input tokens", self.input_tokens),
            ("output tokens", self.output_tokens),
            ("cost", self.cost_micro_usd),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationError(
                    f"AI call {field} must be a non-negative integer"
                )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, object]:
        created_at = self.created_at or datetime.now(UTC)
        return {
            "provider": self.provider,
            "model": self.model,
            "input_hash": self.input_hash,
            "schema_valid": self.schema_valid,
            "outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_micro_usd": self.cost_micro_usd,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "agent_run_id": self.agent_run_id,
            "created_at": created_at.isoformat(),
        }


class AiCallLogger(Protocol):
    def record(self, call: AiCallRecord) -> None: ...


class JsonAiCallLogger:
    def __init__(
        self,
        logger: StructuredLogger | None = None,
        *,
        hash_tenant: bool = False,
        salt: str = "",
    ) -> None:
        self._logger = logger or StructuredLogger("cairn.ai")
        self._hash_tenant = hash_tenant
        self._salt = salt

    def record(self, call: AiCallRecord) -> None:
        context = log_context(
            correlation_id=call.correlation_id,
            tenant_id=call.tenant_id,
            project_id=call.project_id,
            operation_id=call.agent_run_id,
            hash_tenant=self._hash_tenant,
            salt=self._salt,
        )
        fields = call.to_dict()
        fields.update(context)
        self._logger.emit("model.call.completed", context=fields)
