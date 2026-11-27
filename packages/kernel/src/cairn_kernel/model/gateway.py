"""``ModelGateway`` (R5-02a): composes the deny-list, rate-limiter and
circuit-breaker policies in front of a ``ModelPort`` adapter, validates the
adapter's response against the caller's structured-output contract
(R-AI-01), and logs the call through the kernel's existing per-AI-call
observability (``cairn_kernel.observability.ai``) rather than inventing a
parallel logging path.

Every policy check runs *before* ``adapter.generate`` is called, in the
same order every time (deny-list, then rate limit, then circuit breaker,
then run budget -- R6-04), so a blocked call never reaches the adapter --
this is what lets a test assert the adapter's own call counter stayed at
zero past the block point.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from cairn_kernel.errors import ModelPriceUnavailableError, RunBudgetExceededError
from cairn_kernel.hex.ports import Clock
from cairn_kernel.model.cost import ModelPriceTable, compute_cost_micro_usd, default_price_table
from cairn_kernel.model.policy import CircuitBreaker, DenyListPolicy, RateLimiter
from cairn_kernel.model.ports import ModelPort, ModelRequest, ModelResponse
from cairn_kernel.model.run_budget import RunBudgetPolicy
from cairn_kernel.model.schema import validate_structured_output
from cairn_kernel.observability.ai import AiCallLogger, AiCallRecord, JsonAiCallLogger


@dataclass
class ModelGateway:
    """The single path a caller uses to reach a ``ModelPort`` adapter.

    ``generate`` never returns a schema-invalid response: a response that
    fails ``validate_structured_output`` is rejected (raised), never passed
    through to the caller (R-AI-01). ``price_table`` (R5-02b, 815) turns
    each call's own token counts into a real ``cost_micro_usd`` on the
    ``AiCallRecord`` this gateway logs -- see ``cairn_kernel.model.cost``
    for why that is a small local table rather than a reuse of R1-13's
    cloud-SKU price list. An unpriced (provider, model) pair falls back to
    logging ``cost_micro_usd=0`` (814's placeholder) rather than raising: a
    gap in cost *observability* must never break the model call itself.
    """

    adapter: ModelPort
    clock: Clock
    deny_list: DenyListPolicy = field(default_factory=DenyListPolicy)
    rate_limiter: RateLimiter | None = None
    circuit_breaker: CircuitBreaker | None = None
    run_budget_policy: RunBudgetPolicy = field(default_factory=RunBudgetPolicy)
    ai_call_logger: AiCallLogger = field(default_factory=JsonAiCallLogger)
    price_table: ModelPriceTable = field(default_factory=default_price_table)

    def generate(self, request: ModelRequest) -> ModelResponse:
        now = self.clock.now()
        input_hash = _input_hash(request)
        self.deny_list.check(request)
        if self.rate_limiter is not None:
            self.rate_limiter.check(request.tenant_id, now=now)
        if self.circuit_breaker is not None:
            self.circuit_breaker.check(now=now)
        try:
            self.run_budget_policy.check(request)
        except RunBudgetExceededError:
            self._log(
                request,
                input_hash,
                outcome="RUN_BUDGET_EXCEEDED",
                schema_valid=False,
                response=None,
            )
            raise

        try:
            response = self.adapter.generate(request)
        except Exception:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(now=self.clock.now())
            self._log(request, input_hash, outcome="ERROR", schema_valid=False, response=None)
            raise

        self._record_run_budget(request, response)

        try:
            validate_structured_output(request.structured_output, response.output)
        except Exception:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(now=self.clock.now())
            self._log(
                request, input_hash, outcome="SCHEMA_INVALID", schema_valid=False, response=response
            )
            raise

        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success()
        self._log(request, input_hash, outcome="OK", schema_valid=True, response=response)
        return response

    def _record_run_budget(self, request: ModelRequest, response: ModelResponse) -> None:
        if request.agent_run_id is None:
            return
        self.run_budget_policy.record(
            request.agent_run_id,
            tokens=response.input_tokens + response.output_tokens,
            cost_micro_usd=self._cost_micro_usd(response),
        )

    def _log(
        self,
        request: ModelRequest,
        input_hash: str,
        *,
        outcome: str,
        schema_valid: bool,
        response: ModelResponse | None,
    ) -> None:
        self.ai_call_logger.record(
            AiCallRecord(
                provider=response.provider if response is not None else "unknown",
                model=response.model if response is not None else "unknown",
                input_hash=input_hash,
                schema_valid=schema_valid,
                outcome=outcome,
                latency_ms=response.latency_ms if response is not None else 0,
                input_tokens=response.input_tokens if response is not None else 0,
                output_tokens=response.output_tokens if response is not None else 0,
                cost_micro_usd=self._cost_micro_usd(response),
                correlation_id=request.correlation_id,
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                agent_run_id=request.agent_run_id,
            )
        )

    def _cost_micro_usd(self, response: ModelResponse | None) -> int:
        if response is None:
            return 0
        try:
            return compute_cost_micro_usd(
                self.price_table,
                provider=response.provider,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except ModelPriceUnavailableError:
            return 0


def _input_hash(request: ModelRequest) -> str:
    """Sha256 of the prompt and declared schema name -- stable, and never
    includes anything an adapter would need to execute a privileged action,
    because ``ModelRequest`` carries no such field."""

    digest = hashlib.sha256()
    digest.update(request.prompt.encode("utf-8"))
    digest.update(b"\0")
    digest.update(request.structured_output.schema_name.encode("utf-8"))
    return digest.hexdigest()


__all__ = ["ModelGateway"]
