"""ADR-020 §4: the optional policy-substrate port, its no-op default, and
the fixed order :func:`evaluate_tool_call` runs its three checks in.

Two claims this file exists to prove, both from the brief:

1. **The default adapter changes no behaviour.** ``NoOpGovernance``
   allows every check, records nothing, and is what every other test in
   this repository runs against -- so "CAIRN works fully without it"
   (ADR-020 §4) is tested, not asserted.
2. **A test adapter can deny a call.** Separately for each of the three
   checks, with the reason surfaced, so a denial says *which* layer
   denied.

A recording adapter stands in for the real one, which does not exist and
is not built here: no client, SDK or commercial code for any external
governance system is in this repository.
"""

from __future__ import annotations

import pytest
from cairn_kernel.errors import ForbiddenError, ValidationError
from cairn_kernel.governance import (
    GovernanceCheck,
    GovernanceDecision,
    GovernanceDeniedError,
    GovernanceOutcome,
    GovernanceRequest,
    NoOpGovernance,
    evaluate_tool_call,
    require_tool_call_allowed,
)
from cairn_kernel.hex import TenantId
from cairn_kernel.security import Principal, Role

TENANT = "11111111-1111-4111-8111-111111111111"


def _request(**overrides: object) -> GovernanceRequest:
    kwargs: dict[str, object] = {
        "tenant_id": TENANT,
        "actor": "user-1",
        "actor_roles": (Role.VIEWER.value,),
        "tool_name": "estate.list_workloads",
        "capability": "READ",
    }
    kwargs.update(overrides)
    return GovernanceRequest(**kwargs)  # type: ignore[arg-type]


class RecordingGovernance:
    """A test adapter: records which checks it was asked, and denies the
    one named at construction (none, by default)."""

    def __init__(
        self,
        *,
        deny: GovernanceCheck | None = None,
        reason: str = "denied by the test adapter",
    ) -> None:
        self.asked: list[GovernanceCheck] = []
        self.recorded: list[tuple[GovernanceRequest, GovernanceDecision]] = []
        self._deny = deny
        self._reason = reason

    def _answer(self, check: GovernanceCheck) -> GovernanceDecision:
        self.asked.append(check)
        if self._deny is check:
            return GovernanceDecision.deny(check, reason=self._reason, decision_id="rec-1")
        return GovernanceDecision.allow(check)

    def check_revocation(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return self._answer(GovernanceCheck.REVOCATION)

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return self._answer(GovernanceCheck.POLICY)

    def check_budget(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return self._answer(GovernanceCheck.BUDGET)

    def record(self, request: GovernanceRequest, decision: GovernanceDecision) -> None:
        self.recorded.append((request, decision))


class ExplodingGovernance(NoOpGovernance):
    """An adapter that cannot reach its own store."""

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        raise RuntimeError("policy store unreachable")


# -- the no-op default ------------------------------------------------


def test_the_default_adapter_allows_every_check() -> None:
    governance = NoOpGovernance()
    request = _request()

    for check in (
        governance.check_revocation,
        governance.check_policy,
        governance.check_budget,
    ):
        assert check(request).allowed


def test_the_default_adapter_allows_a_tool_call_and_records_nothing() -> None:
    """ "Records nothing" is deliberate and is not a swallowed write:
    there is no external system to record to, and CAIRN's own audit
    ledger and evidence envelopes (ADR-008) already record what CAIRN
    decided, independently of this port."""

    decision = evaluate_tool_call(NoOpGovernance(), _request())

    assert decision.outcome is GovernanceOutcome.ALLOW
    assert NoOpGovernance().record(_request(), decision) is None


def test_the_default_adapter_does_not_raise_from_the_raising_helper() -> None:
    assert require_tool_call_allowed(NoOpGovernance(), _request()).allowed


# -- a test adapter can deny ------------------------------------------


@pytest.mark.parametrize(
    "denied_check",
    [GovernanceCheck.REVOCATION, GovernanceCheck.POLICY, GovernanceCheck.BUDGET],
)
def test_an_adapter_can_deny_any_one_of_the_three_checks(
    denied_check: GovernanceCheck,
) -> None:
    governance = RecordingGovernance(deny=denied_check, reason="over the ceiling")

    decision = evaluate_tool_call(governance, _request())

    assert decision.outcome is GovernanceOutcome.DENY
    assert decision.check is denied_check
    assert decision.reason == "over the ceiling"
    assert decision.decision_id == "rec-1"


def test_a_denial_raises_through_the_helper_the_call_sites_use() -> None:
    governance = RecordingGovernance(deny=GovernanceCheck.BUDGET, reason="over the ceiling")

    with pytest.raises(GovernanceDeniedError) as exc_info:
        require_tool_call_allowed(governance, _request(tool_name="design.generate_target_model"))

    assert "design.generate_target_model" in str(exc_info.value)
    assert "BUDGET" in str(exc_info.value)
    assert "over the ceiling" in str(exc_info.value)
    assert exc_info.value.decision is not None
    assert exc_info.value.decision.check is GovernanceCheck.BUDGET


def test_a_denial_is_a_forbidden_error_so_it_needs_no_new_error_code() -> None:
    """``ForbiddenError`` maps to 403 through the API's existing
    ``STATUS_BY_CODE``: a denied call is a denied call, whether the
    gateway's own role check or an external substrate refused it."""

    assert issubclass(GovernanceDeniedError, ForbiddenError)


# -- the order, and what it means -------------------------------------


def test_the_three_checks_run_revocation_then_policy_then_budget() -> None:
    governance = RecordingGovernance()

    evaluate_tool_call(governance, _request())

    assert governance.asked == [
        GovernanceCheck.REVOCATION,
        GovernanceCheck.POLICY,
        GovernanceCheck.BUDGET,
    ]


def test_the_first_denial_stops_the_remaining_checks() -> None:
    """Nothing is learned by asking a further question once the answer
    is no, and asking anyway would let an adapter's second opinion
    overturn its first."""

    governance = RecordingGovernance(deny=GovernanceCheck.REVOCATION)

    evaluate_tool_call(governance, _request())

    assert governance.asked == [GovernanceCheck.REVOCATION]


def test_the_decision_is_recorded_exactly_once_whether_allowed_or_denied() -> None:
    allowing = RecordingGovernance()
    denying = RecordingGovernance(deny=GovernanceCheck.POLICY)

    evaluate_tool_call(allowing, _request())
    evaluate_tool_call(denying, _request())

    assert len(allowing.recorded) == 1
    assert allowing.recorded[0][1].outcome is GovernanceOutcome.ALLOW
    assert len(denying.recorded) == 1
    assert denying.recorded[0][1].outcome is GovernanceOutcome.DENY


def test_the_recorded_request_carries_the_run_context_it_was_given() -> None:
    governance = RecordingGovernance()
    request = _request(
        run_id="run-1", project_id="project-1", correlation_id="corr-1", credential_id="vaid-1"
    )

    evaluate_tool_call(governance, request)

    recorded, _ = governance.recorded[0]
    assert recorded.run_id == "run-1"
    assert recorded.project_id == "project-1"
    assert recorded.correlation_id == "corr-1"
    assert recorded.credential_id == "vaid-1"


def test_an_adapter_that_cannot_reach_its_store_denies_the_call() -> None:
    """Fail closed (A5.7): nothing is caught, so the exception reaches
    the caller and the call is refused. A governance layer that failed
    open would be worse than none, because the deployment believes it
    has one."""

    with pytest.raises(RuntimeError, match="policy store unreachable"):
        evaluate_tool_call(ExplodingGovernance(), _request())


# -- the request and decision values ----------------------------------


def test_a_request_is_built_from_the_authenticated_principal() -> None:
    """No call site unpacks a ``Principal`` by hand, so none can pass a
    tenant the principal does not actually hold."""

    principal = Principal(
        subject="user-1", tenant_id=TenantId(TENANT), roles=(Role.ARCHITECT, Role.VIEWER)
    )

    request = GovernanceRequest.for_tool_call(
        principal=principal,
        tool_name="design.generate_target_model",
        capability="PROPOSE",
        arguments={"project_id": "project-1"},
    )

    assert request.tenant_id == TENANT
    assert request.actor == "user-1"
    assert request.actor_roles == (Role.ARCHITECT.value, Role.VIEWER.value)
    assert request.capability == "PROPOSE"
    assert request.arguments == {"project_id": "project-1"}


@pytest.mark.parametrize("blank_field", ["tenant_id", "actor", "tool_name", "capability"])
def test_a_request_refuses_a_blank_required_field(blank_field: str) -> None:
    with pytest.raises(ValidationError, match=blank_field):
        _request(**{blank_field: "   "})


def test_a_denial_must_carry_a_reason() -> None:
    """A refusal nobody can explain is unactionable, and the reason is
    what ends up in the error the caller sees."""

    with pytest.raises(ValidationError, match="must carry a reason"):
        GovernanceDecision.deny(GovernanceCheck.POLICY, reason="  ")


def test_an_allow_needs_no_reason() -> None:
    assert GovernanceDecision.allow(GovernanceCheck.POLICY).allowed
