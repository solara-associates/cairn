"""R4-01: the risk-tier policy engine (ADR-010).

Contract tests for every tier's happy path, plus deliberate-break tests
proving a mutation missing its required approver role, a missing
risk-acceptance field, or a tier/mutation-class mismatch is rejected
outright -- never silently defaulted or waved through. Mirrors the fixture
style of ``test_execution_transitions.py``, R1-21's own suite for the layer
this one sits on top of.
"""

import pytest
from cairn_kernel.classification.model import CompensationContract, RecoveryStrategy
from cairn_kernel.errors import (
    RequiredApproverRoleMissingError,
    RiskAcceptanceRequiredError,
    RiskTierMismatchError,
    SeparationOfDutiesError,
)
from cairn_kernel.hex.primitives import MutationClass
from cairn_kernel.security.roles import Role
from cairn_modules.approvals.model import ApprovalRecord, ApprovalState
from cairn_modules.risk_policy.model import (
    ApproverSignOff,
    BlastRadiusConfirmation,
    PreflightResult,
    PreflightStatus,
    RiskAcceptance,
    RiskTier,
    authorize_tier,
    tier_for_approval,
    tier_for_mutation_class,
)

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
REVISION_HASH = "sha256:abc123"

PROPOSER = "bob"
OWNER = "alice"
ARCHITECT_ACTOR = "carol"
ENGINEER_ACTOR = "dave"
AUDITOR_ACTOR = "erin"


def _approval(mutation_class: MutationClass, risk_tier: str, **overrides: object) -> ApprovalRecord:
    fields: dict[str, object] = {
        "approval_id": "55555555-5555-5555-5555-555555555555",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "44444444-4444-4444-4444-444444444444",
        "revision_id": REVISION_ID,
        "revision_hash": REVISION_HASH,
        "mutation_class": mutation_class,
        "risk_tier": risk_tier,
        "state": ApprovalState.APPROVED,
        "proposer_actor_id": PROPOSER,
        "approver_actor_id": OWNER,
    }
    fields.update(overrides)
    return ApprovalRecord(**fields)  # type: ignore[arg-type]


def _contract(strategy: RecoveryStrategy) -> CompensationContract:
    return CompensationContract(
        strategy=strategy,
        plan_ref="recovery-plan://example/plan-1",
        preconditions="target resource identified, scoped, trigger and validation checks recorded",
        authority="PROJECT_OWNER",
        evidence="before/after state capture",
        failure_handling="escalate to incident; execution stays FAILED",
    )


def _risk_acceptance(
    *, accepted_by: str = OWNER, blast_radius_by: str = ARCHITECT_ACTOR
) -> RiskAcceptance:
    return RiskAcceptance(
        accepted_by=ApproverSignOff(actor_id=accepted_by, role=Role.PROJECT_OWNER),
        statement="accountable approver accepts residual risk of this irreversible change",
        blast_radius=BlastRadiusConfirmation(
            actor_id=blast_radius_by,
            role=Role.ARCHITECT,
            statement="confirmed: blast radius limited to project X workload Y",
        ),
        preflight=PreflightResult(status=PreflightStatus.RAN, detail="dry-run completed clean"),
    )


# --- tier_for_mutation_class / tier_for_approval ---------------------------


def test_read_only_and_internal_mutation_carry_no_tier() -> None:
    assert tier_for_mutation_class(MutationClass.READ_ONLY) is None
    assert tier_for_mutation_class(MutationClass.INTERNAL_MUTATION) is None


@pytest.mark.parametrize(
    ("mutation_class", "tier"),
    [
        (MutationClass.REVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_1),
        (MutationClass.COMPENSATABLE_EXTERNAL_MUTATION, RiskTier.TIER_2),
        (MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_3),
    ],
)
def test_each_external_mutation_class_maps_to_its_tier(
    mutation_class: MutationClass, tier: RiskTier
) -> None:
    assert tier_for_mutation_class(mutation_class) is tier


def test_tier_for_approval_accepts_a_correctly_declared_tier() -> None:
    approval = _approval(MutationClass.REVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_1.value)
    assert tier_for_approval(approval) is RiskTier.TIER_1


def test_tier_for_approval_rejects_a_mismatched_tier() -> None:
    approval = _approval(MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION, RiskTier.TIER_1.value)
    with pytest.raises(RiskTierMismatchError):
        tier_for_approval(approval)


def test_tier_for_approval_rejects_a_tier_claimed_for_a_tierless_mutation() -> None:
    approval = _approval(MutationClass.INTERNAL_MUTATION, RiskTier.TIER_3.value)
    with pytest.raises(RiskTierMismatchError):
        tier_for_approval(approval)


# --- contract tests: happy path for every tier -----------------------------


def test_tier_1_authorizes_with_one_execution_role_approver_and_rollback_contract() -> None:
    tier = authorize_tier(
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        proposer_actor_id=PROPOSER,
        approvers=(ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),),
        compensation=_contract(RecoveryStrategy.ROLLBACK),
    )
    assert tier is RiskTier.TIER_1


def test_tier_2_authorizes_with_two_approvers_one_holding_execution_role() -> None:
    tier = authorize_tier(
        MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
        proposer_actor_id=PROPOSER,
        approvers=(
            ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
        ),
        compensation=_contract(RecoveryStrategy.COMPENSATE),
    )
    assert tier is RiskTier.TIER_2


def test_tier_3_authorizes_with_accountable_signoff_and_blast_radius_confirmation() -> None:
    tier = authorize_tier(
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        proposer_actor_id=PROPOSER,
        approvers=(
            ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
        ),
        compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
        risk_acceptance=_risk_acceptance(),
    )
    assert tier is RiskTier.TIER_3


def test_read_only_and_internal_mutation_need_no_approvers_at_all() -> None:
    assert (
        authorize_tier(
            MutationClass.READ_ONLY,
            proposer_actor_id=PROPOSER,
            approvers=(),
            compensation=None,
        )
        is None
    )
    assert (
        authorize_tier(
            MutationClass.INTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(),
            compensation=None,
        )
        is None
    )


# --- deliberate-break tests: missing approver role -------------------------


def test_tier_1_rejects_an_approver_without_the_execution_role() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_tier(
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=ENGINEER_ACTOR, role=Role.ENGINEER),),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
        )


def test_tier_1_rejects_zero_approvers() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_tier(
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
        )


def test_tier_2_rejects_a_single_approver() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_tier(
            MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),),
            compensation=_contract(RecoveryStrategy.COMPENSATE),
        )


def test_tier_2_rejects_two_approvers_neither_holding_execution_role() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_tier(
            MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
                ApproverSignOff(actor_id=ENGINEER_ACTOR, role=Role.ENGINEER),
            ),
            compensation=_contract(RecoveryStrategy.COMPENSATE),
        )


def test_tier_3_rejects_a_confirmer_who_is_not_an_architect() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        authorize_tier(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=ENGINEER_ACTOR, role=Role.ENGINEER),
            ),
            compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
            risk_acceptance=_risk_acceptance(blast_radius_by=ENGINEER_ACTOR),
        )


@pytest.mark.parametrize("mutation_class", list(MutationClass))
def test_auditor_and_viewer_can_never_stand_in_as_an_approver(
    mutation_class: MutationClass,
) -> None:
    tier = tier_for_mutation_class(mutation_class)
    if tier is None:
        pytest.skip(f"{mutation_class.value} carries no tier")
    for forbidden_role in (Role.AUDITOR, Role.VIEWER):
        approvers = (ApproverSignOff(actor_id=AUDITOR_ACTOR, role=forbidden_role),)
        with pytest.raises(RequiredApproverRoleMissingError):
            authorize_tier(
                mutation_class,
                proposer_actor_id=PROPOSER,
                approvers=approvers,
                compensation=None,
            )


# --- deliberate-break tests: missing risk-acceptance field (tier 3) -------


def test_tier_3_rejects_a_missing_risk_acceptance_outright() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_tier(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
            ),
            compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
            risk_acceptance=None,
        )


def test_tier_3_rejects_risk_acceptance_signed_by_someone_other_than_the_accountable_approver() -> (
    None
):
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_tier(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
            ),
            compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
            # signed by the blast-radius confirmer, not the accountable approver
            risk_acceptance=_risk_acceptance(accepted_by=ARCHITECT_ACTOR),
        )


def test_tier_3_rejects_a_rollback_promise_even_with_risk_acceptance_present() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_tier(
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
            ),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
            risk_acceptance=_risk_acceptance(),
        )


def test_risk_acceptance_statement_must_not_be_blank() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        RiskAcceptance(
            accepted_by=ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            statement="   ",
            blast_radius=BlastRadiusConfirmation(
                actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT, statement="confirmed"
            ),
            preflight=PreflightResult(status=PreflightStatus.RAN, detail="ran clean"),
        )


def test_blast_radius_confirmation_statement_must_not_be_blank() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        BlastRadiusConfirmation(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT, statement="")


def test_preflight_result_detail_must_not_be_blank() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        PreflightResult(status=PreflightStatus.NOT_SUPPORTED_BY_PROVIDER, detail="")


def test_tier_3_accepts_an_explicitly_declared_unsupported_preflight() -> None:
    tier = authorize_tier(
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        proposer_actor_id=PROPOSER,
        approvers=(
            ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
        ),
        compensation=_contract(RecoveryStrategy.ACCEPT_IRREVERSIBLE),
        risk_acceptance=RiskAcceptance(
            accepted_by=ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
            statement="accepted; provider has no dry-run capability for this operation",
            blast_radius=BlastRadiusConfirmation(
                actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT, statement="confirmed scope"
            ),
            preflight=PreflightResult(
                status=PreflightStatus.NOT_SUPPORTED_BY_PROVIDER,
                detail="provider API has no dry-run mode for this operation",
            ),
        ),
    )
    assert tier is RiskTier.TIER_3


# --- deliberate-break tests: separation of duties --------------------------


def test_proposer_cannot_also_be_an_approver() -> None:
    with pytest.raises(SeparationOfDutiesError):
        authorize_tier(
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=PROPOSER, role=Role.PROJECT_OWNER),),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
        )


def test_the_same_actor_cannot_hold_two_approver_signoffs() -> None:
    with pytest.raises(SeparationOfDutiesError):
        authorize_tier(
            MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=OWNER, role=Role.ARCHITECT),
            ),
            compensation=_contract(RecoveryStrategy.COMPENSATE),
        )


def test_approver_signoff_rejects_a_blank_actor_id() -> None:
    with pytest.raises(RequiredApproverRoleMissingError):
        ApproverSignOff(actor_id="   ", role=Role.PROJECT_OWNER)


# --- recovery precondition is required before role enforcement proceeds ---


def test_tier_1_rejects_a_missing_compensation_contract() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_tier(
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),),
            compensation=None,
        )


def test_tier_2_rejects_the_wrong_recovery_strategy() -> None:
    with pytest.raises(RiskAcceptanceRequiredError):
        authorize_tier(
            MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
            proposer_actor_id=PROPOSER,
            approvers=(
                ApproverSignOff(actor_id=OWNER, role=Role.PROJECT_OWNER),
                ApproverSignOff(actor_id=ARCHITECT_ACTOR, role=Role.ARCHITECT),
            ),
            compensation=_contract(RecoveryStrategy.ROLLBACK),
        )
