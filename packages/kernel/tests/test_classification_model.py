import pytest
from cairn_kernel.classification import (
    CompensationContract,
    OperationEntry,
    RecoveryStrategy,
    SurfaceKind,
    operations_by_name,
    require_classified,
)
from cairn_kernel.classification.matrix import OPERATIONS
from cairn_kernel.errors import (
    CoverageIncompleteError,
    MutationClassMismatchError,
    RecoveryPlanRequiredError,
)
from cairn_kernel.hex.primitives import MutationClass, OperationClass
from cairn_kernel.tenancy.classification import TenancyScope

# These two helpers build a hypothetical Class C entry purely to exercise the
# compensation-contract mechanism. No such operation exists in R0 (no Class C
# adapter is wired before R4, ADR-010) and this fixture is not part of the
# real matrix in cairn_kernel.classification.matrix.


def _valid_compensation() -> CompensationContract:
    return CompensationContract(
        strategy=RecoveryStrategy.ROLLBACK,
        plan_ref="recovery-plan://example/rollback-1",
        preconditions="target resource identified and scoped",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


def test_matrix_entries_are_internally_consistent() -> None:
    index = operations_by_name(OPERATIONS)
    assert len(index) == len(OPERATIONS)


def test_operation_rejects_mismatched_operation_and_mutation_class() -> None:
    with pytest.raises(MutationClassMismatchError):
        OperationEntry(
            surface=SurfaceKind.API,
            name="example.GET /thing",
            operation_class=OperationClass.READ,
            mutation_class=MutationClass.INTERNAL_MUTATION,
            tenancy_scope=TenancyScope.GLOBAL,
        )


def test_internal_mutation_must_not_carry_a_compensation_contract() -> None:
    with pytest.raises(MutationClassMismatchError):
        OperationEntry(
            surface=SurfaceKind.EVENT,
            name="example.recorded.v1",
            operation_class=OperationClass.WORKSPACE_MUTATION,
            mutation_class=MutationClass.INTERNAL_MUTATION,
            tenancy_scope=TenancyScope.PROJECT,
            compensation=_valid_compensation(),
        )


def test_external_mutation_without_compensation_is_rejected() -> None:
    with pytest.raises(RecoveryPlanRequiredError):
        OperationEntry(
            surface=SurfaceKind.MCP_TOOL,
            name="example.hypothetical_class_c_tool",
            operation_class=OperationClass.GOVERNED_ENV_MUTATION,
            mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            tenancy_scope=TenancyScope.PROJECT,
        )


def test_external_mutation_with_complete_compensation_is_accepted() -> None:
    entry = OperationEntry(
        surface=SurfaceKind.MCP_TOOL,
        name="example.hypothetical_class_c_tool",
        operation_class=OperationClass.GOVERNED_ENV_MUTATION,
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        tenancy_scope=TenancyScope.PROJECT,
        compensation=_valid_compensation(),
    )
    assert entry.compensation is not None


def test_compensation_strategy_must_match_the_mutation_class() -> None:
    mismatched = CompensationContract(
        strategy=RecoveryStrategy.COMPENSATE,
        plan_ref="recovery-plan://example/rollback-1",
        preconditions="target resource identified and scoped",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )
    with pytest.raises(MutationClassMismatchError):
        OperationEntry(
            surface=SurfaceKind.MCP_TOOL,
            name="example.hypothetical_class_c_tool",
            operation_class=OperationClass.GOVERNED_ENV_MUTATION,
            mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            tenancy_scope=TenancyScope.PROJECT,
            compensation=mismatched,
        )


def test_compensation_contract_rejects_blank_fields() -> None:
    with pytest.raises(RecoveryPlanRequiredError):
        CompensationContract(
            strategy=RecoveryStrategy.ROLLBACK,
            plan_ref="recovery-plan://example/rollback-1",
            preconditions="  ",
            authority="PROJECT_OWNER",
            evidence="before/after state capture",
            failure_handling="escalate to incident; execution stays FAILED",
        )


def test_only_class_c_may_defer_its_mutation_class() -> None:
    with pytest.raises(MutationClassMismatchError):
        OperationEntry(
            surface=SurfaceKind.API,
            name="example.GET /thing",
            operation_class=OperationClass.READ,
            mutation_class=None,
            tenancy_scope=TenancyScope.GLOBAL,
            defer_reason="not a real reason",
        )


def test_deferred_mutation_class_requires_a_reason() -> None:
    with pytest.raises(MutationClassMismatchError):
        OperationEntry(
            surface=SurfaceKind.EVENT,
            name="example.started.v1",
            operation_class=OperationClass.GOVERNED_ENV_MUTATION,
            mutation_class=None,
            tenancy_scope=TenancyScope.PROJECT,
        )


def test_require_classified_raises_coverage_incomplete_for_unknown_surface() -> None:
    index = operations_by_name(OPERATIONS)
    with pytest.raises(CoverageIncompleteError):
        require_classified(index, SurfaceKind.API, "api.GET /v1/not-a-real-endpoint")


def test_require_classified_passes_for_a_real_matrix_entry() -> None:
    index = operations_by_name(OPERATIONS)
    require_classified(index, SurfaceKind.API, "api.GET /healthz")
