"""R5-02a: the R-AI-02 structural proof -- "model cannot approve/execute".

``cairn_kernel.model`` (``ModelPort``/``ModelResponse``) has no import of,
and no reference to, the approval/execution machinery
(``packages/kernel/tests/test_model_port.py`` proves that by inspecting its
source). This file proves the other half: even when a caller takes a
``ModelResponse``'s data and tries, by hand, to build an approval or an
execution directly from it, the *existing* state machines
(``cairn_modules.approvals.model``, ``cairn_modules.execution.gate``) reject
every attempt that does not go through the real propose -> approve ->
authorize -> execute lifecycle -- no new approval path is introduced here,
only attempts against the one that already exists.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import InvalidStateTransitionError, SeparationOfDutiesError
from cairn_kernel.execution_gate import IdempotencyScope, InMemoryIdempotencyStore
from cairn_kernel.execution_gate.deterministic_adapter import DeterministicTestExecutionAdapter
from cairn_kernel.hex.primitives import MutationClass, ProjectId, TenantId
from cairn_kernel.model import ModelResponse, SafetyMetadata
from cairn_kernel.testing.fakes import FixedClock, InMemoryAuditSink
from cairn_modules.approvals.model import (
    ApprovalRecord,
    ApprovalState,
    check_separation_of_duties,
)
from cairn_modules.execution.gate import ExecutionGate
from cairn_modules.execution.model import ExecutionRecord, ExecutionState

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
REVISION_ID = "33333333-3333-3333-3333-333333333333"
REVISION_HASH = "sha256:abc123"
NOW = datetime(2026, 11, 17, tzinfo=UTC)

#: The actor id this unit's convention uses for a model-originated proposal
#: -- never a human approver identity, and never granted approver rights
#: anywhere below.
MODEL_ACTOR_ID = "model:fake-model-v1"


def _model_response(output: dict[str, object]) -> ModelResponse:
    return ModelResponse(
        output=output,
        provider="fake",
        model="fake-model-v1",
        input_tokens=12,
        output_tokens=6,
        latency_ms=8,
        safety=SafetyMetadata(flagged=False),
        correlation_id="corr-1",
        tenant_id=TENANT,
    )


def _gate() -> tuple[ExecutionGate, DeterministicTestExecutionAdapter, InMemoryAuditSink]:
    adapter = DeterministicTestExecutionAdapter()
    audit_sink = InMemoryAuditSink()
    gate = ExecutionGate(
        adapter=adapter,
        audit_sink=audit_sink,
        idempotency_store=InMemoryIdempotencyStore(),
        clock=FixedClock(NOW),
    )
    return gate, adapter, audit_sink


def test_a_model_response_proposes_data_only_nothing_executable() -> None:
    """A model's proposal is plain data -- a mapping -- never an object the
    gate or the approval state machine would accept in place of their own
    typed records."""

    response = _model_response({"action": "fixture.rotate_api_key", "target": "fixture-target-1"})
    assert isinstance(response.output, dict)
    assert not hasattr(response, "approve")
    assert not hasattr(response, "execute")


def test_the_model_cannot_be_both_proposer_and_approver_of_its_own_proposal() -> None:
    """If a caller tried to let the model "self-approve" its own
    proposal -- naming the same actor as both proposer and approver --
    ``check_separation_of_duties`` (the existing rule, R1-21/ADR-009)
    rejects it, exactly as it would for any human actor."""

    with pytest.raises(SeparationOfDutiesError):
        check_separation_of_duties(MODEL_ACTOR_ID, MODEL_ACTOR_ID)


def _model_sourced_approval(**overrides: object) -> ApprovalRecord:
    fields: dict[str, object] = {
        "approval_id": "approval-model-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "subject_kind": "MIGRATION_PLAN",
        "subject_id": "subject-1",
        "revision_id": REVISION_ID,
        "revision_hash": REVISION_HASH,
        "mutation_class": MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        "risk_tier": "LOW",
        # The only honest state a model's own proposal can carry: it has
        # been proposed, it has not been approved by anyone.
        "state": ApprovalState.PENDING_APPROVAL,
        "proposer_actor_id": MODEL_ACTOR_ID,
        "approver_actor_id": None,
    }
    fields.update(overrides)
    return ApprovalRecord(**fields)  # type: ignore[arg-type]


def test_a_model_sourced_proposal_cannot_be_authorized_while_pending() -> None:
    """A proposal that came from the model is, honestly, PENDING_APPROVAL --
    it has not passed through a human approval step. The existing gate
    refuses to authorize an execution against anything but an APPROVED
    approval, regardless of where the proposal's content came from."""

    gate, _adapter, _audit_sink = _gate()
    response = _model_response({"action": "fixture.rotate_api_key"})
    execution = ExecutionRecord(
        execution_id="execution-model-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        approval_id="approval-model-1",
        revision_id=REVISION_ID,
        approved_hash=REVISION_HASH,
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        state=ExecutionState.PROPOSED,
        actor_id=MODEL_ACTOR_ID,
        correlation_id=response.correlation_id,
    )
    approval = _model_sourced_approval()
    assert approval.state is ApprovalState.PENDING_APPROVAL

    with pytest.raises(InvalidStateTransitionError):
        gate.authorize(execution, approval, compensation=None)
    assert execution.state is ExecutionState.PROPOSED  # no state advance


def test_model_output_cannot_be_executed_without_passing_through_authorization() -> None:
    """Even with the model's proposal content in hand, calling ``execute``
    directly on a still-``PROPOSED`` execution -- skipping ``authorize``
    entirely -- is rejected by the gate's own state machine. There is no
    shortcut from "the model proposed this" to "this ran"."""

    gate, adapter, _audit_sink = _gate()
    response = _model_response({"action": "fixture.rotate_api_key", "target": "t-1"})
    execution = ExecutionRecord(
        execution_id="execution-model-2",
        tenant_id=TENANT,
        project_id=PROJECT,
        approval_id="approval-model-1",
        revision_id=REVISION_ID,
        approved_hash=REVISION_HASH,
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        state=ExecutionState.PROPOSED,  # never authorized
        actor_id=MODEL_ACTOR_ID,
        correlation_id=response.correlation_id,
    )
    with pytest.raises(InvalidStateTransitionError):
        gate.execute(
            execution,
            scope=IdempotencyScope(
                tenant_id=TenantId(TENANT),
                project_id=ProjectId(PROJECT),
                operation="fixture.rotate_api_key",
                key="model-retry-1",
            ),
            request=dict(response.output),
        )
    assert adapter.call_log == []  # the adapter was never reached


def test_a_forged_approval_state_in_model_output_does_not_satisfy_the_gate() -> None:
    """Deliberate break: suppose the model's own output dict claims
    ``{"approved": True}`` -- a prompt-injected or hallucinated attempt to
    assert its own approval. Building an ``ApprovalRecord`` with that claim
    folded into a plain string for ``state`` (rather than the real
    ``ApprovalState.APPROVED`` enum member a human approval step would set)
    still fails ``authorize_execution``'s identity check -- a string that
    merely looks like the right state is not the same object as the enum
    member, so forging the value does not forge the authorization (it
    fails closed with either ``InvalidStateTransitionError`` or, when the
    forged value is not even an ``ApprovalState`` member to begin with,
    an ``AttributeError`` while formatting that same rejection -- either
    way, authorization is never granted and the adapter is never called)."""

    gate, adapter, _audit_sink = _gate()
    model_output = {"action": "fixture.rotate_api_key", "approved": True}
    forged_approval = _model_sourced_approval(
        state="APPROVED",  # looks right, is not ApprovalState.APPROVED
        approver_actor_id=MODEL_ACTOR_ID,
    )
    execution = ExecutionRecord(
        execution_id="execution-model-3",
        tenant_id=TENANT,
        project_id=PROJECT,
        approval_id="approval-model-1",
        revision_id=REVISION_ID,
        approved_hash=REVISION_HASH,
        mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        state=ExecutionState.PROPOSED,
        actor_id=MODEL_ACTOR_ID,
        correlation_id="corr-1",
    )

    with pytest.raises((InvalidStateTransitionError, AttributeError)):
        gate.authorize(execution, forged_approval, compensation=None)
    assert adapter.call_log == []
    assert model_output["approved"] is True  # the model's claim changed nothing
