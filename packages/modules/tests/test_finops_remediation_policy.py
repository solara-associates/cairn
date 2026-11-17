"""R5-01a: FinOps graded remediation policy (unit 812).

Contract tests for each grade (alert/throttle carry no mutation class and no
approval gate; cap/stop/disable each require their mapped tier's approver
role), plus a deliberate-break test proving a ``stop``/``disable`` action
cannot bypass its assigned tier's required-approver-role check -- it must be
rejected outright, never silently defaulted to allow. Mirrors the fixture
style of ``test_risk_policy.py``, the suite for the layer this one calls
into.
"""

import pytest
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import RequiredApproverRoleMissingError, ValidationError
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.security.roles import Role
from cairn_modules.finops.remediation_policy import (
    CLASS_C_GRADES,
    RemediationAction,
    RemediationGrade,
    authorize_remediation,
    mutation_class_for_grade,
    tier_for_grade,
)
from cairn_modules.risk_policy.model import ApproverSignOff, RiskTier

OWNER = "alice"
PROPOSER = "bob"
ARCHITECT_ACTOR = "carol"
ENGINEER_ACTOR = "dave"


def _action(grade: RemediationGrade) -> RemediationAction:
    return RemediationAction(
        grade=grade, resource_ref="gcp://project-1/compute/vm-7", reason="budget exceeded forecast"
    )


def _rollback_contract() -> CompensationContract:
    return CompensationContract(
        strategy=RecoveryStrategy.ROLLBACK,
        plan_ref="recovery-plan://finops/restore-prior-cap",
        preconditions="target resource identified, scoped, trigger and validation checks recorded",
        authority="PROJECT_OWNER",
        evidence="before/after cap value capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


def _compensate_contract() -> CompensationContract:
    return CompensationContract(
        strategy=RecoveryStrategy.COMPENSATE,
        plan_ref="recovery-plan://finops/reconcile-dropped-work",
        preconditions="dropped in-flight work identified, scope and reconciliation steps recorded",
        authority="PROJECT_OWNER",
        evidence="before/after resource state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


# --- grading: mutation class / tier mapping --------------------------------


@pytest.mark.parametrize("grade", [RemediationGrade.ALERT, RemediationGrade.THROTTLE])
def test_alert_and_throttle_carry_no_mutation_class_or_tier(grade: RemediationGrade) -> None:
    assert mutation_class_for_grade(grade) is None
    assert tier_for_grade(grade) is None


@pytest.mark.parametrize(
    ("grade", "mutation_class", "tier"),
    [
        (RemediationGrade.CAP, MutationClass.REVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_1),
        (RemediationGrade.DISABLE, MutationClass.REVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_1),
        (RemediationGrade.STOP, MutationClass.COMPENSATABLE_EXTERNAL_MUTATION, RiskTier.TIER_2),
    ],
)
def test_class_c_grades_map_to_their_documented_tier(
    grade: RemediationGrade, mutation_class: MutationClass, tier: RiskTier
) -> None:
    assert mutation_class_for_grade(grade) is mutation_class
    assert tier_for_grade(grade) is tier
    assert grade in CLASS_C_GRADES


def test_alert_and_throttle_are_not_class_c() -> None:
    assert RemediationGrade.ALERT not in CLASS_C_GRADES
    assert RemediationGrade.THROTTLE not in CLASS_C_GRADES


# --- RemediationAction validation ------------------------------------------


def test_remediation_action_rejects_a_blank_resource_ref() -> None:
    with pytest.raises(ValidationError):
        RemediationAction(grade=RemediationGrade.ALERT, resource_ref="  ", reason="budget alert")


def test_remediation_action_rejects_a_blank_reason() -> None:
    with pytest.raises(ValidationError):
        RemediationAction(
            grade=RemediationGrade.ALERT, resource_ref="gcp://project-1/vm-7", reason=" "
        )


def test_remediation_action_exposes_mutation_class_and_is_class_c() -> None:
    assert _action(RemediationGrade.ALERT).mutation_class is None
    assert _action(RemediationGrade.ALERT).is_class_c is False
    assert (
        _action(RemediationGrade.CAP).mutation_class is MutationClass.REVERSIBLE_EXTERNAL_MUTATION
    )
    assert _action(RemediationGrade.CAP).is_class_c is True


# --- contract tests: no-mutation grades need no approval gate --------------


@pytest.mark.parametrize("grade", [RemediationGrade.ALERT, RemediationGrade.THROTTLE])
def test_alert_and_throttle_authorize_with_no_approvers_at_all(grade: RemediationGrade) -> None:
    result = authorize_remediation(_action(grade), proposer_actor_id=PROPOSER)
    assert result is None


# --- contract tests: Class C grades require their mapped tier's approver --


def test_cap_authorizes_as_tier_1_with_one_execution_role_approver() -> None:
    tier = authorize_remediation(
        _action(RemediationGrade.CAP),
        proposer_actor_id=PROPOSER,
        approvers=(ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),),
        compensation=_rollback_contract(),
    )
    assert tier is RiskTier.TIER_1


def test_disable_authorizes_as_tier_1_with_one_execution_role_approver() -> None:
    tier = authorize_remediation(
        _action(RemediationGrade.DISABLE),
        proposer_actor_id=PROPOSER,
        approvers=(ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),),
        compensation=_rollback_contract(),
    )
    assert tier is RiskTier.TIER_1


def test_stop_authorizes_as_tier_2_with_two_approvers_one_holding_execution_role() -> None:
    tier = authorize_remediation(
        _action(RemediationGrade.STOP),
        proposer_actor_id=PROPOSER,
        approvers=(
            ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
        ),
        compensation=_compensate_contract(),
    )
    assert tier is RiskTier.TIER_2


# --- deliberate-break tests: cannot bypass the mapped tier's role check ----


def test_disable_action_cannot_bypass_tier_1_required_approver_role() -> None:
    """A DISABLE that reaches a non-qualifying role must be rejected
    outright, not silently defaulted to allow."""

    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_remediation(
            _action(RemediationGrade.DISABLE),
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=ENGINEER_ACTOR, role=Role.ENGINEER),),
            compensation=_rollback_contract(),
        )


def test_stop_action_cannot_bypass_tier_2_required_approver_role() -> None:
    """A STOP with two approvers, neither holding the tier's required
    execution role, must be rejected outright, not silently defaulted to
    allow."""

    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_remediation(
            _action(RemediationGrade.STOP),
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
                ApproverSignOff(actor_id=ENGINEER_ACTOR, role=Role.ENGINEER),
            ),
            compensation=_compensate_contract(),
        )


def test_cap_action_cannot_proceed_with_zero_approvers() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_remediation(
            _action(RemediationGrade.CAP),
            proposer_actor_id=PROPOSER,
            approvers=(),
            compensation=_rollback_contract(),
        )


def test_disable_action_cannot_be_approved_by_its_own_proposer() -> None:
    """Separation of duties, enforced by risk_policy, applies here too --
    the proposer cannot stand in as the sole approver."""

    from cairn_kernel.errors import SeparationOfDutiesError

    with pytest.raises(SeparationOfDutiesError):
        authorize_remediation(
            _action(RemediationGrade.DISABLE),
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=PROPOSER, role=Role.PROJECT_OWNER),),
            compensation=_rollback_contract(),
        )
