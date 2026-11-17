"""R5-02a: ``ModelPort`` (ADR-014) -- the port, its request/response
contract, request/response policy enforcement (deny-list, rate limit,
circuit breaker) and schema validation (R-AI-01). No concrete adapter
lives here: the kernel is a leaf (``.importlinter``'s "Kernel and
contracts are leaves" contract), and the mandatory fake adapter is
``cairn_adapters.model.FakeModelAdapter``.

R-AI-02 ("model cannot approve/execute"): nothing in this package imports
``cairn_kernel.execution_gate``, ``cairn_modules.approvals`` or
``cairn_modules.execution`` -- there is no path from here into
approval/execution authority, by construction, and
``packages/kernel/tests/test_model_port.py`` asserts this with an AST
import check the same way ``cairn_kernel.execution_gate``'s own tests
assert "no execution credentials reachable".
"""

from cairn_kernel.model.gateway import ModelGateway
from cairn_kernel.model.policy import CircuitBreaker, CircuitState, DenyListPolicy, RateLimiter
from cairn_kernel.model.ports import (
    ModelPort,
    ModelRequest,
    ModelResponse,
    SafetyMetadata,
    SafetyParameters,
    StructuredOutputExpectation,
)
from cairn_kernel.model.schema import validate_structured_output

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "DenyListPolicy",
    "ModelGateway",
    "ModelPort",
    "ModelRequest",
    "ModelResponse",
    "RateLimiter",
    "SafetyMetadata",
    "SafetyParameters",
    "StructuredOutputExpectation",
    "validate_structured_output",
]
