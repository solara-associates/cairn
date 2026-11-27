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

from cairn_kernel.model.control_loop import (
    CostControlBudget,
    CostControlDecision,
    CostControlEvaluation,
    CostControlLoop,
    evaluate_cost_window,
)
from cairn_kernel.model.cost import (
    ModelPriceRate,
    ModelPriceTable,
    compute_cost_micro_usd,
    default_price_table,
)
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
from cairn_kernel.model.run_budget import RunBudgetLimits, RunBudgetPolicy
from cairn_kernel.model.schema import validate_structured_output

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CostControlBudget",
    "CostControlDecision",
    "CostControlEvaluation",
    "CostControlLoop",
    "DenyListPolicy",
    "ModelGateway",
    "ModelPort",
    "ModelPriceRate",
    "ModelPriceTable",
    "ModelRequest",
    "ModelResponse",
    "RateLimiter",
    "RunBudgetLimits",
    "RunBudgetPolicy",
    "SafetyMetadata",
    "SafetyParameters",
    "StructuredOutputExpectation",
    "compute_cost_micro_usd",
    "default_price_table",
    "evaluate_cost_window",
    "validate_structured_output",
]
