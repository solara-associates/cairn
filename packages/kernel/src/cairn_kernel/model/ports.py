"""``ModelPort`` (ADR-014, R5-02a): the kernel's outbound port for calling a
language model.

ADR-014's contract is deliberately narrow: a prompt, a structured-output
expectation, safety parameters going in; a structured output, token/latency
telemetry and safety metadata coming back -- "no authority to perform
irreversible actions". Nothing in this module names a target resource to
mutate, carries a credential, or exposes a second method a caller could use
to approve or execute anything. A model call can only ever produce a
*proposal*; turning a proposal into an approved, executed action is the
existing approval/execution machinery's job
(``cairn_modules.approvals.model``, ``cairn_modules.execution.gate``), not
this port's (R-AI-02) -- see
``packages/modules/tests/test_model_proposal_boundary.py`` for the
structural proof, and ``packages/kernel/tests/test_model_port.py`` for the
import-boundary proof that this package cannot even reach that machinery.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import Port


@dataclass(frozen=True, slots=True)
class SafetyParameters:
    """Safety configuration sent with every request (ADR-014: "safety
    metadata"). ``disallowed_categories`` names content categories the
    caller requires the provider to refuse; ``max_output_tokens`` bounds
    runaway generation. Nothing here, or anywhere in this module, grants
    the model authority over anything but its own output."""

    max_output_tokens: int
    disallowed_categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.max_output_tokens, int) or isinstance(self.max_output_tokens, bool):
            raise ValidationError("max_output_tokens must be an integer")
        if self.max_output_tokens <= 0:
            raise ValidationError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class StructuredOutputExpectation:
    """What shape the caller expects the model's output to take -- the
    contract R-AI-01 validates a response against.

    ``schema`` is a minimal JSON-Schema-shaped mapping:
    ``{"type": "object", "required": [...], "properties": {name: {"type":
    ...}}}``. Only object schemas are supported: enough to validate the
    proposal shapes this unit's callers declare, without this port growing
    a general-purpose JSON Schema implementation (ADR-014 asks for
    "structured output expectations", not an open-ended schema language).
    """

    schema_name: str
    schema: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.schema_name.strip():
            raise ValidationError("structured output expectation needs a schema_name")
        if self.schema.get("type") != "object":
            raise ValidationError("structured output expectation must declare type: object")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Everything ``ModelPort.generate`` needs, and nothing it does not.

    Deliberately absent: any approval/execution authority, any credential,
    any field naming a resource to mutate (ADR-014: "no authority to
    perform irreversible actions"). A caller hands the model a prompt and
    asks for a structured proposal; it is never handed a way to act on one.
    """

    prompt: str
    structured_output: StructuredOutputExpectation
    safety: SafetyParameters
    tenant_id: str
    correlation_id: str
    project_id: str | None = None
    agent_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValidationError("model request prompt must not be blank")
        if not self.tenant_id.strip():
            raise ValidationError("model request tenant_id is required")
        if not self.correlation_id.strip():
            raise ValidationError("model request correlation_id is required")


@dataclass(frozen=True, slots=True)
class SafetyMetadata:
    """ADR-014's "safety metadata" on the response side: did the provider
    flag the output, and against which category."""

    flagged: bool
    categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """``ModelPort.generate``'s result: the parsed structured output,
    token/latency telemetry and safety metadata (ADR-014) -- and, by
    construction, nothing else.

    There is no ``approve``/``execute``/``authorize`` method, no approval-
    state field, and no reference to ``ExecutionAdapterPort`` or
    ``ApprovalRecord`` anywhere on this type: it cannot grant authority to
    act (R-AI-02), only describe what the model produced. A caller wanting
    to act on ``output`` must build its own
    ``cairn_modules.approvals.model.ApprovalRecord`` from this data and
    pass that through the existing approval/execution gate like any other
    proposed action -- nothing here does that for them, and nothing here
    imports the types that would let it.
    """

    output: Mapping[str, object]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    safety: SafetyMetadata
    correlation_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("correlation_id", self.correlation_id),
            ("tenant_id", self.tenant_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"model response {field_name} is required")
        for field_name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("latency_ms", self.latency_ms),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValidationError(f"model response {field_name} must be a non-negative integer")
        if not isinstance(self.output, Mapping):
            raise ValidationError("model response output must be a mapping")


class ModelPort(Port, Protocol):
    """Outbound port every model call goes through (ADR-014).

    Exactly one method: there is no second method on this ``Protocol`` that
    could be (mis)used to approve or execute anything. The structural
    guarantee R-AI-02 asks for starts at the port's own shape --
    ``packages/kernel/tests/test_model_port.py`` asserts this directly.
    """

    def generate(self, request: ModelRequest) -> ModelResponse: ...


__all__ = [
    "ModelPort",
    "ModelRequest",
    "ModelResponse",
    "SafetyMetadata",
    "SafetyParameters",
    "StructuredOutputExpectation",
]
