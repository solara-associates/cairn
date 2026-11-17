"""R5-05a: failover rule evaluation (resilience).

Builds on R1-06/R1-07's canonical ``Workload``/``Dependency`` model
(``cairn_contracts.estate.model``, ``cairn_modules.estate.workloads``) without
extending or modifying it. R2's ``resilient-multi-region`` pattern
(``patterns/resilient-multi-region.yaml``) already describes *provisioning*
a multi-region topology (regions, trigger mode, DR-drill cadence) -- it does
not declare a *per-workload* failover target, so it has nothing this module
can reuse directly; this module's ``FailoverPolicy`` is the missing,
narrower piece that sits underneath a provisioned topology like that one.

Judgement calls (per the brief: "you'll need to define this policy shape...
keep it minimal and real, not speculative"):

* **Policy shape**: a ``FailoverPolicy`` declares, for one protected
  workload, a ``primary_target_workload_id`` and an optional
  ``secondary_target_workload_id`` -- exactly the brief's own suggested
  shape. Both must be real, distinct workload ids different from the
  protected workload itself (enforced at construction). This module does
  not require the declared targets to also appear as a canonical
  ``Dependency`` edge -- a failover target is a statement about *where
  traffic goes next*, which is a narrower, policy-level fact than the
  estate model's dependency graph (which records *what a workload already
  calls*, observed from infrastructure facts, not declared intent). Forcing
  the two to coincide would either require inventing a new
  ``DependencyKind`` on the canonical contract (out of scope -- a shared
  contract other R5 units also build on) or silently reusing an existing
  kind for a meaning it doesn't carry. Keeping them separate is the
  minimal, honest reading.
* **No declared policy at all -- "ungoverned"**: a workload with no entry
  in the policy map is never defaulted to "healthy" or quietly dropped from
  an evaluation run. ``evaluate_estate_failover`` evaluates every workload
  it is given, in the estate's own order, and an ungoverned workload always
  produces an explicit ``FailoverOutcome.UNGOVERNED`` result -- fail closed,
  never fail silent.
* **Secondary failure ("both primary and secondary unavailable")**: this
  returns ``FailoverOutcome.NO_VIABLE_TARGET`` with
  ``selected_target_workload_id=None`` -- an explicit, typed "nothing to
  fail over to" result, not an exception and not a guess at a third
  target the policy never declared. The same outcome covers "primary down,
  no secondary declared" (there was never a second target to try), with a
  distinct ``reason`` string so the two cases read differently to a human
  even though the typed outcome is the same -- there was always exactly
  one well-defined fallback slot, never an invented chain beyond it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from enum import Enum

from cairn_contracts.estate.model import Workload
from pydantic import BaseModel, ConfigDict, model_validator


class FailoverOutcome(str, Enum):
    #: The primary target is available; no failover is needed.
    PRIMARY_HEALTHY = "PRIMARY_HEALTHY"
    #: The primary target is unavailable; the declared secondary target is
    #: available and is the correct failover target.
    FAILED_OVER_TO_SECONDARY = "FAILED_OVER_TO_SECONDARY"
    #: The primary target is unavailable and there is no viable fallback --
    #: either no secondary was declared, or the secondary is unavailable too.
    NO_VIABLE_TARGET = "NO_VIABLE_TARGET"
    #: No ``FailoverPolicy`` is declared for this workload at all. Fails
    #: closed: never treated as already resilient, never skipped.
    UNGOVERNED = "UNGOVERNED"


class FailoverPolicy(BaseModel):
    """A workload's own declared failover targets.

    ``workload_id`` is the protected workload. ``primary_target_workload_id``
    is the workload it currently fails over through first;
    ``secondary_target_workload_id`` is the one further fallback this
    module's evaluation recognises -- ``None`` means the workload's own
    policy declares no secondary, which is itself a real, honest policy (not
    the same as no policy at all).
    """

    model_config = ConfigDict(frozen=True)

    workload_id: str
    primary_target_workload_id: str
    secondary_target_workload_id: str | None = None

    @model_validator(mode="after")
    def _targets_are_distinct(self) -> FailoverPolicy:
        if self.primary_target_workload_id == self.workload_id:
            raise ValueError("a workload's primary failover target must not be itself")
        if self.secondary_target_workload_id is not None:
            if self.secondary_target_workload_id == self.workload_id:
                raise ValueError("a workload's secondary failover target must not be itself")
            if self.secondary_target_workload_id == self.primary_target_workload_id:
                raise ValueError(
                    "a workload's secondary failover target must differ from its primary"
                )
        return self


class FailoverResult(BaseModel):
    """The outcome of evaluating one workload's failover policy against a
    synthetic failure injection."""

    model_config = ConfigDict(frozen=True)

    workload_id: str
    outcome: FailoverOutcome
    selected_target_workload_id: str | None
    reason: str


#: A policy lookup keyed by the protected workload's id.
FailoverPolicyMap = Mapping[str, FailoverPolicy]


def evaluate_failover(
    workload_id: str,
    policies: FailoverPolicyMap,
    unavailable_workload_ids: AbstractSet[str],
) -> FailoverResult:
    """Evaluate one workload's declared failover policy against the set of
    workload ids marked unavailable by a synthetic failure injection.

    Looks up ``workload_id`` in ``policies`` only -- never infers a target
    from the estate's dependency graph, and never treats a missing policy
    as "nothing to do here".
    """
    policy = policies.get(workload_id)
    if policy is None:
        return FailoverResult(
            workload_id=workload_id,
            outcome=FailoverOutcome.UNGOVERNED,
            selected_target_workload_id=None,
            reason="no failover policy is declared for this workload -- ungoverned, fails closed",
        )

    if policy.primary_target_workload_id not in unavailable_workload_ids:
        return FailoverResult(
            workload_id=workload_id,
            outcome=FailoverOutcome.PRIMARY_HEALTHY,
            selected_target_workload_id=policy.primary_target_workload_id,
            reason="primary target is available",
        )

    secondary = policy.secondary_target_workload_id
    if secondary is not None and secondary not in unavailable_workload_ids:
        return FailoverResult(
            workload_id=workload_id,
            outcome=FailoverOutcome.FAILED_OVER_TO_SECONDARY,
            selected_target_workload_id=secondary,
            reason="primary target unavailable; failed over to the declared secondary target",
        )

    if secondary is None:
        reason = "primary target unavailable and no secondary target is declared"
    else:
        reason = "primary and declared secondary targets are both unavailable"
    return FailoverResult(
        workload_id=workload_id,
        outcome=FailoverOutcome.NO_VIABLE_TARGET,
        selected_target_workload_id=None,
        reason=reason,
    )


def evaluate_estate_failover(
    workloads: Sequence[Workload],
    policies: FailoverPolicyMap,
    unavailable_workload_ids: AbstractSet[str],
) -> tuple[FailoverResult, ...]:
    """Evaluate every workload in ``workloads``, in a stable order.

    Every workload passed in gets exactly one ``FailoverResult`` -- an
    ungoverned workload (no entry in ``policies``) is reported as
    ``FailoverOutcome.UNGOVERNED``, never omitted from the run.
    """
    return tuple(
        evaluate_failover(workload.workload_id, policies, unavailable_workload_ids)
        for workload in sorted(workloads, key=lambda w: w.workload_id)
    )


__all__ = [
    "FailoverOutcome",
    "FailoverPolicy",
    "FailoverPolicyMap",
    "FailoverResult",
    "evaluate_estate_failover",
    "evaluate_failover",
]
