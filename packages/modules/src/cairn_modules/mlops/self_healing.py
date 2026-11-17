"""R5-03b: MLOps self-healing with bounds.

Given 816's (``cairn_modules.mlops.model``) drift-detection result and a
history of prior self-healing actions (retrains, rollbacks) taken for a
model/version, decide whether a *new* self-healing action is allowed right
now, or whether it has exceeded its configured bound and must instead
escalate to a human decision.

Pure domain model: no adapter, no I/O (``cairn_modules`` is a leaf consumer
of ``cairn_kernel`` only, per ``.importlinter``'s ``domain-purity``
contract) -- same convention as ``cairn_modules.mlops.model``.

Judgement calls:

* **Mutation class: Class B, not Class C.** Per ADR-010's operation-class
  table, a self-healing action that retrains or rolls back a model is
  itself a governed mutation. This codebase has no real serving/deployment
  infrastructure anywhere (no ``ProviderExecutionPort`` call for a model
  deploy target exists or is implied) -- so *both* ``RETRAIN`` and
  ``ROLLBACK`` are treated here as ``INTERNAL_MUTATION`` (ADR-010 Class B):
  a workspace decision that updates the registry's own record of what
  happened, recorded for future wiring. This is deliberately **not** a
  real Class C call through ``ProviderExecutionPort`` -- that would need
  cloud/real serving infra this unit does not have and is out of scope.
  ``SelfHealingDecision.mutation_class`` is hard-coded to
  ``"INTERNAL_MUTATION"`` to make this framing explicit and inspectable,
  not left to the caller to infer.
* **The bound is a hard ceiling, not a soft suggestion -- and it is the
  attempt past it that trips, not the bound-th attempt itself.** Mirrors
  816's own fail-closed boundary convention (there: a drift delta exactly
  at the threshold *counts* as drift, i.e. the threshold is the maximum
  tolerated movement and is itself still tolerated only up to and
  including that value). Applied here: a bound of 3 means "3 actions may
  happen in the window" -- the 3rd action is still within bounds (it is
  the action *that reaches* the bound), and only the 4th attempt, which
  would exceed it, is rejected. Concretely: with 2 prior actions already
  recorded in the window, a new attempt is allowed (reaching the bound of
  3); with 3 prior actions already recorded, a new attempt is rejected
  outright. This matches the brief's own worked example verbatim ("a 4th
  retrain attempt in a window that only allows 3 is REJECTED") and keeps
  the bound counting prior *completed* actions, not the attempt being
  evaluated -- so the bound is never silently capped, queued or
  soft-defaulted past its line.
* **Escalation is a raised error, not a return value.** Matching 816's
  error-handling style (``ValidationError``/``NotFoundError`` raised, never
  a silent default), an action that exceeds its bound raises
  ``SelfHealingBoundExceededError`` rather than returning e.g. an
  ``allowed=False`` decision object. The caller (a future human-approval
  flow) catches it and escalates; there is no path by which an
  over-the-bound action is silently allowed, capped, or queued for later.
* **No drift, no trigger.** A self-healing action only makes sense as a
  *response* to detected drift. ``evaluate_self_healing_trigger`` requires
  a ``DriftReport`` with ``drifted is True`` and raises ``ValidationError``
  otherwise -- fail closed rather than letting a caller fire a retrain or
  rollback with no drift to justify it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from cairn_kernel.errors import ValidationError

from cairn_modules.mlops.model import DriftReport

#: ADR-010 mutation class every self-healing action in this unit is
#: recorded under -- see the module docstring's "Class B, not Class C"
#: judgement call. Never used for a real deploy/serving-target mutation.
SELF_HEALING_MUTATION_CLASS = "INTERNAL_MUTATION"


class SelfHealingBoundExceededError(ValidationError):
    """Raised when a self-healing action would exceed its configured bound.

    Fail closed: the action is rejected outright -- not silently capped to
    the bound, not queued for later, not defaulted to allowed. The caller
    must escalate to a human decision instead.
    """

    title = "Self-healing bound exceeded"


class SelfHealingActionType(str, Enum):
    """The two self-healing actions this unit bounds."""

    RETRAIN = "retrain"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class SelfHealingBounds:
    """Per-window bounds on automatic self-healing actions.

    ``window`` is a sliding window ending at the decision time (``now``):
    an action counts toward the bound if it occurred at or after
    ``now - window``.
    """

    max_retrains_per_window: int
    max_rollbacks_per_window: int
    window: timedelta

    def __post_init__(self) -> None:
        if self.max_retrains_per_window < 1:
            raise ValidationError("max_retrains_per_window must be at least 1")
        if self.max_rollbacks_per_window < 1:
            raise ValidationError("max_rollbacks_per_window must be at least 1")
        if self.window <= timedelta(0):
            raise ValidationError("window must be a positive duration")

    def limit_for(self, action_type: SelfHealingActionType) -> int:
        if action_type is SelfHealingActionType.RETRAIN:
            return self.max_retrains_per_window
        if action_type is SelfHealingActionType.ROLLBACK:
            return self.max_rollbacks_per_window
        raise ValidationError(f"unknown self-healing action type {action_type!r}")


@dataclass(frozen=True, slots=True)
class SelfHealingActionRecord:
    """One prior self-healing action taken for a model/version, by
    timestamp -- the history this unit's trigger logic bounds against."""

    action_type: SelfHealingActionType
    model_id: str
    version: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SelfHealingDecision:
    """An allowed self-healing action, recorded as a Class B workspace
    decision (see the module docstring's mutation-class judgement call).

    This is not itself an execution -- it is the governed decision that a
    retrain or rollback may proceed. ``prior_actions_in_window`` and
    ``bound`` are carried for evidence/audit: they are the exact numbers
    the decision was made against.
    """

    action_type: SelfHealingActionType
    model_id: str
    version: str
    mutation_class: str
    prior_actions_in_window: int
    bound: int


def evaluate_self_healing_trigger(
    drift_report: DriftReport,
    action_type: SelfHealingActionType,
    bounds: SelfHealingBounds,
    history: Sequence[SelfHealingActionRecord],
    *,
    now: datetime,
) -> SelfHealingDecision:
    """Decide whether a new self-healing action is allowed right now.

    ``drift_report`` must report drift (``drifted is True``) -- a
    self-healing action is only triggered as a response to detected
    drift. ``history`` is every prior self-healing action recorded across
    all models/versions; only entries matching ``drift_report.model_id``,
    ``drift_report.version`` and ``action_type``, within
    ``bounds.window`` of ``now``, count toward the bound.

    Returns a ``SelfHealingDecision`` when the action is within bounds.
    Raises ``SelfHealingBoundExceededError`` when it would exceed the
    bound -- see the module docstring's boundary judgement call for
    exactly which attempt trips it. Raises ``ValidationError`` when
    ``drift_report`` reports no drift.
    """

    if not drift_report.drifted:
        raise ValidationError(
            "no drift detected -- a self-healing action requires a drifted"
            " DriftReport to trigger on"
        )

    window_start = now - bounds.window
    prior_in_window = [
        record
        for record in history
        if record.action_type is action_type
        and record.model_id == drift_report.model_id
        and record.version == drift_report.version
        and window_start <= record.occurred_at <= now
    ]
    count = len(prior_in_window)
    bound = bounds.limit_for(action_type)

    if count >= bound:
        raise SelfHealingBoundExceededError(
            f"{action_type.value} for model {drift_report.model_id!r} version"
            f" {drift_report.version!r} exceeds its bound: {count} action(s)"
            f" already recorded in the last {bounds.window} (bound is {bound});"
            " escalate to a human decision instead"
        )

    return SelfHealingDecision(
        action_type=action_type,
        model_id=drift_report.model_id,
        version=drift_report.version,
        mutation_class=SELF_HEALING_MUTATION_CLASS,
        prior_actions_in_window=count,
        bound=bound,
    )


__all__ = [
    "SELF_HEALING_MUTATION_CLASS",
    "SelfHealingActionRecord",
    "SelfHealingActionType",
    "SelfHealingBoundExceededError",
    "SelfHealingBounds",
    "SelfHealingDecision",
    "evaluate_self_healing_trigger",
]
