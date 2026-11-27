"""ADR-020 §4: the port an optional external policy substrate attaches
behind, and the types it decides over.

ADR-020 §4 records that the commercial, optional system named in
``docs/specs/r5-integration-boundaries.md`` -- should an adapter for it
ever be built -- attaches as an **adapter behind a port**, never inside
``cairn_kernel``, and never as something a tenant-scope check (§2) or a
VAID verification (§3) depends on to function. This module is that port
and nothing else. **No client, no SDK, no commercial code, and no
decision logic lives here or anywhere in this repository**; the real
adapter comes later, from that system's own side.

**CAIRN works fully without it, and that is the default.** Every control
ADR-019 and ADR-020 describe -- role and tenant authorization,
``RunBudget``, the evidence envelope, the approval and execution gates --
is implemented in CAIRN core today with no dependency on this port.
:class:`NoOpGovernance` is bound unless a deployment binds something
else, and it allows every call and records nothing, so a deployment with
no adapter loses nothing CAIRN itself promises. It simply has no optional
extra policy, budget or revocation layer bolted on.

**Why this port is in the kernel when its adapter cannot be.** The port
is a shape; the adapter is an integration. Both the MCP gateway (an app)
and the agent loop (``cairn_kits``) have to call this, and neither may
import the other, so the shape has to live in the one leaf package both
already depend on -- the same reason ``Principal`` itself lives here.
``cairn_kernel`` importing nothing to define it is what keeps that true:
there is no import here that a vendor could ever appear in.

**The four concerns, and the one order they run in.** ADR-020 §4 names
four: a policy decision before a tool call, a budget check, a revocation
check, and a record of what was decided. Each is its own method, so an
adapter cannot answer one question while appearing to answer another, and
:func:`evaluate_tool_call` composes them in a fixed order every caller
shares:

1. **revocation** -- has this authority been withdrawn? A withdrawn
   credential should not go on to be policy-evaluated at all, and
   "withdrawn" is the answer least likely to be recoverable by retrying.
2. **policy** -- is this call permitted?
3. **budget** -- is there headroom left to make it?

First denial wins and the rest are not consulted: there is nothing to
learn from asking a further question once the answer is no, and asking
anyway would let an adapter's second opinion overturn its first. The
decision is then recorded exactly once, whatever it was -- a record only
of denials would be a log that cannot answer "was this call allowed, and
by what".

**A raising adapter denies.** :func:`evaluate_tool_call` does not catch
anything: an adapter that cannot reach its own store must raise, and that
exception propagates to the caller, which refuses the call. A governance
layer that fails open is worse than none, because the deployment believes
it has one (A5.7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from cairn_kernel.errors import ForbiddenError, ValidationError
from cairn_kernel.hex.primitives import Port
from cairn_kernel.security import Principal


class GovernanceOutcome(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class GovernanceCheck(str, Enum):
    """Which of the port's questions produced a decision.

    Carried on the decision so a denial says *which* layer denied --
    "over budget" and "credential withdrawn" are different operational
    facts, and collapsing them into one boolean is how an on-call
    engineer ends up unable to tell a policy change from an outage.
    """

    POLICY = "POLICY"
    BUDGET = "BUDGET"
    REVOCATION = "REVOCATION"


class GovernanceDeniedError(ForbiddenError):
    """The governance layer denied a tool call.

    A ``ForbiddenError`` subclass, so it maps to 403 through the API's
    existing ``STATUS_BY_CODE`` without a new error code: a denied call
    is a denied call, whether the gateway's own role check denied it or
    an external policy substrate did.
    """

    title = "Denied by governance policy"

    def __init__(self, detail: str = "", *, decision: GovernanceDecision | None = None) -> None:
        super().__init__(detail)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class GovernanceRequest:
    """What the port is asked to decide about: one tool call, by one
    authenticated principal, in one tenant.

    Deliberately a flat value of its own rather than a ``Principal``
    plus loose arguments. Two reasons. It is the port's contract, so an
    adapter outside this repository must not have to import
    ``cairn_kernel``'s own types to read a field; and it is what gets
    recorded, so everything a record needs has to be on it -- an adapter
    that had to reach back for context could not have written the record
    in the first place.

    ``capability`` is the tool's declared ``ToolCapability`` as a plain
    string (``"READ"``/``"PROPOSE"``). A string, not the enum: that enum
    lives in ``cairn_kits``, which this package may not import (it is a
    leaf), and an external adapter should not need it either.

    ``credential_id`` is the id of the credential that proved the actor
    where there is one -- a verified VAID's ``vaid_id`` (ADR-020 §3).
    This is the field a revocation check is actually about: a bearer
    token has nothing stable to revoke, a VAID does.
    """

    tenant_id: str
    actor: str
    actor_roles: tuple[str, ...]
    tool_name: str
    capability: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    credential_id: str | None = None
    run_id: str | None = None
    project_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_id", self.tenant_id),
            ("actor", self.actor),
            ("tool_name", self.tool_name),
            ("capability", self.capability),
        ):
            if not value.strip():
                raise ValidationError(f"governance request {name} must not be blank")

    @classmethod
    def for_tool_call(
        cls,
        *,
        principal: Principal,
        tool_name: str,
        capability: str,
        arguments: Mapping[str, object] | None = None,
        credential_id: str | None = None,
        run_id: str | None = None,
        project_id: str | None = None,
        correlation_id: str | None = None,
    ) -> GovernanceRequest:
        """Build a request from the gateway's own authenticated
        ``Principal``, so no call site has to unpack it by hand and
        none can pass a tenant the principal does not actually hold."""

        return cls(
            tenant_id=principal.tenant_id.value,
            actor=principal.subject,
            actor_roles=principal.role_values(),
            tool_name=tool_name,
            capability=capability,
            arguments=dict(arguments or {}),
            credential_id=credential_id,
            run_id=run_id,
            project_id=project_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    """One decision, and why.

    ``decision_id`` is whatever the adapter's own tamper-evident record
    is keyed by, where it keeps one, so a CAIRN-side audit entry can
    point at the external record rather than paraphrasing it.
    """

    outcome: GovernanceOutcome
    check: GovernanceCheck
    reason: str = ""
    decision_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome is GovernanceOutcome.ALLOW

    @classmethod
    def allow(
        cls, check: GovernanceCheck, *, reason: str = "", decision_id: str | None = None
    ) -> GovernanceDecision:
        return cls(
            outcome=GovernanceOutcome.ALLOW,
            check=check,
            reason=reason,
            decision_id=decision_id,
        )

    @classmethod
    def deny(
        cls, check: GovernanceCheck, *, reason: str, decision_id: str | None = None
    ) -> GovernanceDecision:
        """A denial must carry a reason -- a refusal nobody can explain
        is unactionable, and ``reason`` is what ends up in the error the
        caller sees."""

        if not reason.strip():
            raise ValidationError("a governance denial must carry a reason")
        return cls(
            outcome=GovernanceOutcome.DENY,
            check=check,
            reason=reason,
            decision_id=decision_id,
        )


class GovernancePort(Port, Protocol):
    """The optional policy substrate seam (ADR-020 §4).

    An implementation must either answer or raise. It must never mutate
    CAIRN state, and it is never consulted *instead of* a check CAIRN
    already performs -- the gateway's role check and every bounded-context
    server's tenant check (ADR-020 §2) run regardless of what is bound
    here, which is why nothing bound here can widen what a caller may do.
    This port can only ever deny.
    """

    def check_revocation(self, request: GovernanceRequest) -> GovernanceDecision: ...

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision: ...

    def check_budget(self, request: GovernanceRequest) -> GovernanceDecision: ...

    def record(self, request: GovernanceRequest, decision: GovernanceDecision) -> None: ...


class NoOpGovernance:
    """The default adapter: allows everything, records nothing.

    This is what makes ADR-020 §4's "CAIRN works fully without it" true
    rather than aspirational. It is bound unless a deployment binds
    something else, and it is what every test in this repository runs
    against, so the no-governance path is the tested path.

    It allows rather than denies, and that is not a fail-open hole: the
    port is an *extra* layer that can only subtract authority. Nothing a
    caller may do depends on it saying yes -- authentication,
    authorization and tenant scope have all already run, or will, no
    matter what is bound here. A default that denied would simply break
    a deployment that never asked for governance at all.
    """

    def check_revocation(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return GovernanceDecision.allow(
            GovernanceCheck.REVOCATION, reason="no governance adapter is bound"
        )

    def check_policy(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return GovernanceDecision.allow(
            GovernanceCheck.POLICY, reason="no governance adapter is bound"
        )

    def check_budget(self, request: GovernanceRequest) -> GovernanceDecision:
        del request
        return GovernanceDecision.allow(
            GovernanceCheck.BUDGET, reason="no governance adapter is bound"
        )

    def record(self, request: GovernanceRequest, decision: GovernanceDecision) -> None:
        """Deliberately nothing.

        Not a silent swallow: there is no external record to write
        because there is no external system, and CAIRN's own audit
        ledger and evidence envelopes (ADR-008) already record what
        CAIRN itself decided, independently of this port. Writing a
        second, weaker copy here would be the lie, not this.
        """

        del request, decision


def evaluate_tool_call(
    governance: GovernancePort, request: GovernanceRequest
) -> GovernanceDecision:
    """Run the port's three checks in their fixed order, record the
    decision exactly once, and return it.

    First denial wins; the remaining checks are not consulted. The
    returned decision is always recorded, allow or deny, so the record
    answers "was this call allowed, and by what" rather than only
    listing refusals.

    Nothing is caught: an adapter that raises denies the call, because a
    governance layer that fails open is worse than none (A5.7). See this
    module's docstring for why this order.
    """

    for check in (
        governance.check_revocation,
        governance.check_policy,
        governance.check_budget,
    ):
        decision = check(request)
        if not decision.allowed:
            governance.record(request, decision)
            return decision
    governance.record(request, decision)
    return decision


def require_tool_call_allowed(
    governance: GovernancePort, request: GovernanceRequest
) -> GovernanceDecision:
    """:func:`evaluate_tool_call`, raising :class:`GovernanceDeniedError`
    on a denial instead of returning it.

    What the gateway and the agent loop both call: at those two seams
    there is nothing useful to do with a denial except refuse, and a
    returned-but-ignored denial is the failure mode this exists to make
    impossible.
    """

    decision = evaluate_tool_call(governance, request)
    if not decision.allowed:
        raise GovernanceDeniedError(
            f"governance denied {request.tool_name!r} for actor {request.actor!r}"
            f" ({decision.check.value}): {decision.reason}",
            decision=decision,
        )
    return decision


__all__ = [
    "GovernanceCheck",
    "GovernanceDecision",
    "GovernanceDeniedError",
    "GovernanceOutcome",
    "GovernancePort",
    "GovernanceRequest",
    "NoOpGovernance",
    "evaluate_tool_call",
    "require_tool_call_allowed",
]
