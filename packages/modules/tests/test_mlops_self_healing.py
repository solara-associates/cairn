"""R5-03b: bounded self-healing trigger logic.

Covers: a deliberate-break test proving an action exceeding its configured
bound (a 4th retrain attempt in a window that only allows 3) is rejected
outright, not silently capped, queued, or defaulted to allowed; a
positive-path test proving an action within bounds is allowed; a boundary
test proving the bound-th action is still within bounds and only the next
attempt past it trips the limit (documented in
``cairn_modules.mlops.self_healing`` as this module's own fail-closed
boundary convention, mirroring 816's drift-threshold boundary); and that
no-drift input is rejected rather than silently triggering an action.
"""

from datetime import UTC, datetime, timedelta

import pytest
from cairn_kernel.errors import ValidationError
from cairn_modules.mlops.model import DriftReport, MetricDrift
from cairn_modules.mlops.self_healing import (
    SELF_HEALING_MUTATION_CLASS,
    SelfHealingActionRecord,
    SelfHealingActionType,
    SelfHealingBoundExceededError,
    SelfHealingBounds,
    evaluate_self_healing_trigger,
)

NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)


def _drifted_report(model_id: str = "risk-scorer", version: str = "1.0.0") -> DriftReport:
    return DriftReport(
        model_id=model_id,
        version=version,
        metrics=(
            MetricDrift(
                metric="accuracy",
                baseline_value=0.92,
                current_value=0.70,
                delta=-0.22,
                threshold=0.1,
                drifted=True,
            ),
        ),
    )


def _clean_report(model_id: str = "risk-scorer", version: str = "1.0.0") -> DriftReport:
    return DriftReport(
        model_id=model_id,
        version=version,
        metrics=(
            MetricDrift(
                metric="accuracy",
                baseline_value=0.92,
                current_value=0.92,
                delta=0.0,
                threshold=0.1,
                drifted=False,
            ),
        ),
    )


def _history(count: int, *, action_type=SelfHealingActionType.RETRAIN, within_window=True) -> tuple:
    offset = timedelta(minutes=5) if within_window else timedelta(days=30)
    return tuple(
        SelfHealingActionRecord(
            action_type=action_type,
            model_id="risk-scorer",
            version="1.0.0",
            occurred_at=NOW - offset - timedelta(minutes=i),
        )
        for i in range(count)
    )


def _bounds(max_retrains: int = 3, max_rollbacks: int = 1) -> SelfHealingBounds:
    return SelfHealingBounds(
        max_retrains_per_window=max_retrains,
        max_rollbacks_per_window=max_rollbacks,
        window=timedelta(hours=24),
    )


def test_action_within_bounds_is_allowed() -> None:
    report = _drifted_report()
    bounds = _bounds(max_retrains=3)
    history = _history(1)  # one prior retrain, well under the bound of 3

    decision = evaluate_self_healing_trigger(
        report, SelfHealingActionType.RETRAIN, bounds, history, now=NOW
    )

    assert decision.action_type is SelfHealingActionType.RETRAIN
    assert decision.model_id == "risk-scorer"
    assert decision.version == "1.0.0"
    assert decision.mutation_class == SELF_HEALING_MUTATION_CLASS == "INTERNAL_MUTATION"
    assert decision.prior_actions_in_window == 1
    assert decision.bound == 3


def test_fourth_retrain_attempt_exceeding_bound_of_three_is_rejected_outright() -> None:
    report = _drifted_report()
    bounds = _bounds(max_retrains=3)
    history = _history(3)  # 3 retrains already recorded in the window

    with pytest.raises(SelfHealingBoundExceededError):
        evaluate_self_healing_trigger(
            report, SelfHealingActionType.RETRAIN, bounds, history, now=NOW
        )


def test_boundary_the_bound_th_action_is_allowed_only_the_next_attempt_trips() -> None:
    """Bound of 3: with 2 prior actions, this attempt (the 3rd) is allowed
    -- it reaches the bound, it does not exceed it. With 3 prior actions,
    the next attempt (the 4th) is rejected. See the module docstring's
    boundary judgement call."""

    report = _drifted_report()
    bounds = _bounds(max_retrains=3)

    decision = evaluate_self_healing_trigger(
        report, SelfHealingActionType.RETRAIN, bounds, _history(2), now=NOW
    )
    assert decision.prior_actions_in_window == 2
    assert decision.bound == 3

    with pytest.raises(SelfHealingBoundExceededError):
        evaluate_self_healing_trigger(
            report, SelfHealingActionType.RETRAIN, bounds, _history(3), now=NOW
        )


def test_rejection_is_not_silently_capped_queued_or_defaulted_allowed() -> None:
    """The deliberate-break assertion in full: an over-bound action raises,
    it does not return any decision object at all (capped, queued, or
    otherwise), and it is a named error, not a generic/base one."""

    report = _drifted_report()
    bounds = _bounds(max_retrains=3)
    history = _history(5)  # well past the bound

    with pytest.raises(SelfHealingBoundExceededError) as excinfo:
        result = evaluate_self_healing_trigger(
            report, SelfHealingActionType.RETRAIN, bounds, history, now=NOW
        )
        # Unreachable if the fail-closed contract holds -- guards against a
        # future regression that returns a capped/queued decision instead
        # of raising.
        assert result is None

    assert excinfo.type is SelfHealingBoundExceededError
    assert "exceeds its bound" in str(excinfo.value)


def test_actions_outside_the_window_do_not_count_toward_the_bound() -> None:
    report = _drifted_report()
    bounds = _bounds(max_retrains=3)
    history = _history(5, within_window=False)  # all 30+ days old, outside a 24h window

    decision = evaluate_self_healing_trigger(
        report, SelfHealingActionType.RETRAIN, bounds, history, now=NOW
    )

    assert decision.prior_actions_in_window == 0


def test_rollback_and_retrain_bounds_are_independent() -> None:
    report = _drifted_report()
    bounds = _bounds(max_retrains=3, max_rollbacks=1)
    retrain_history = _history(3, action_type=SelfHealingActionType.RETRAIN)

    # Retrains are at their bound, but rollback has its own separate bound
    # and no prior rollbacks recorded -- it is still allowed.
    decision = evaluate_self_healing_trigger(
        report, SelfHealingActionType.ROLLBACK, bounds, retrain_history, now=NOW
    )
    assert decision.prior_actions_in_window == 0
    assert decision.bound == 1

    with pytest.raises(SelfHealingBoundExceededError):
        evaluate_self_healing_trigger(
            report, SelfHealingActionType.RETRAIN, bounds, retrain_history, now=NOW
        )


def test_different_model_version_history_does_not_count_toward_bound() -> None:
    report = _drifted_report(model_id="risk-scorer", version="2.0.0")
    bounds = _bounds(max_retrains=3)
    # 3 prior retrains, but for a different version of the model.
    history = _history(3)

    decision = evaluate_self_healing_trigger(
        report, SelfHealingActionType.RETRAIN, bounds, history, now=NOW
    )

    assert decision.prior_actions_in_window == 0


def test_no_drift_rejects_the_trigger() -> None:
    report = _clean_report()
    bounds = _bounds()

    with pytest.raises(ValidationError):
        evaluate_self_healing_trigger(report, SelfHealingActionType.RETRAIN, bounds, (), now=NOW)


def test_bounds_reject_non_positive_configuration() -> None:
    with pytest.raises(ValidationError):
        SelfHealingBounds(
            max_retrains_per_window=0,
            max_rollbacks_per_window=1,
            window=timedelta(hours=1),
        )
    with pytest.raises(ValidationError):
        SelfHealingBounds(
            max_retrains_per_window=1,
            max_rollbacks_per_window=0,
            window=timedelta(hours=1),
        )
    with pytest.raises(ValidationError):
        SelfHealingBounds(
            max_retrains_per_window=1,
            max_rollbacks_per_window=1,
            window=timedelta(0),
        )
