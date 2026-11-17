"""R5-05a: failover rule evaluation.

Contract tests for a primary-failure scenario (primary marked unavailable,
correct declared secondary target returned) and a secondary-failure
scenario (both primary and secondary unavailable -- an explicit "no viable
target" result, never a crash or a guess), plus a deliberate-break test
proving a workload with no declared failover policy at all is reported as
``UNGOVERNED`` by ``evaluate_estate_failover`` -- never silently treated as
already resilient, and never dropped from the evaluation run.
"""

from __future__ import annotations

import pytest
from cairn_contracts.estate.model import Workload
from cairn_modules.resilience.model import (
    FailoverOutcome,
    FailoverPolicy,
    evaluate_estate_failover,
    evaluate_failover,
)
from pydantic import ValidationError

TENANT = "tenant-a"
PROJECT = "project-a"

PRIMARY_DB = "wl-db-primary"
SECONDARY_DB = "wl-db-secondary"
TERTIARY_DB = "wl-db-tertiary"
UNGOVERNED_APP = "wl-app-ungoverned"


def _workload(workload_id: str) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name=workload_id,
        environment="prod",
        owner=None,
        business_context=None,
        resource_ids=(f"res-{workload_id}",),
        dependency_ids=(),
        facts={},
        disposition=None,
        disposition_confidence=None,
        model_version="r5-05a-test",
        mapping_version="r5-05a-test",
    )


def test_primary_failure_returns_declared_secondary() -> None:
    policy = FailoverPolicy(
        workload_id=PRIMARY_DB,
        primary_target_workload_id=PRIMARY_DB + "-az1",
        secondary_target_workload_id=SECONDARY_DB,
    )
    policies = {PRIMARY_DB: policy}

    result = evaluate_failover(
        PRIMARY_DB,
        policies,
        unavailable_workload_ids={PRIMARY_DB + "-az1"},
    )

    assert result.outcome is FailoverOutcome.FAILED_OVER_TO_SECONDARY
    assert result.selected_target_workload_id == SECONDARY_DB


def test_primary_healthy_returns_primary_no_failover_needed() -> None:
    policy = FailoverPolicy(
        workload_id=PRIMARY_DB,
        primary_target_workload_id=PRIMARY_DB + "-az1",
        secondary_target_workload_id=SECONDARY_DB,
    )
    policies = {PRIMARY_DB: policy}

    result = evaluate_failover(PRIMARY_DB, policies, unavailable_workload_ids=set())

    assert result.outcome is FailoverOutcome.PRIMARY_HEALTHY
    assert result.selected_target_workload_id == PRIMARY_DB + "-az1"


def test_secondary_also_unavailable_returns_no_viable_target_explicitly() -> None:
    primary_az = PRIMARY_DB + "-az1"
    policy = FailoverPolicy(
        workload_id=PRIMARY_DB,
        primary_target_workload_id=primary_az,
        secondary_target_workload_id=SECONDARY_DB,
    )
    policies = {PRIMARY_DB: policy}

    result = evaluate_failover(
        PRIMARY_DB,
        policies,
        unavailable_workload_ids={primary_az, SECONDARY_DB},
    )

    assert result.outcome is FailoverOutcome.NO_VIABLE_TARGET
    assert result.selected_target_workload_id is None
    assert "unavailable" in result.reason


def test_primary_unavailable_with_no_secondary_declared_is_no_viable_target() -> None:
    primary_az = PRIMARY_DB + "-az1"
    policy = FailoverPolicy(workload_id=PRIMARY_DB, primary_target_workload_id=primary_az)
    policies = {PRIMARY_DB: policy}

    result = evaluate_failover(PRIMARY_DB, policies, unavailable_workload_ids={primary_az})

    assert result.outcome is FailoverOutcome.NO_VIABLE_TARGET
    assert result.selected_target_workload_id is None
    assert "no secondary" in result.reason


def test_no_declared_policy_is_ungoverned_not_crash_not_healthy() -> None:
    """Deliberate-break: a workload with zero policy entries must never be
    treated as already resilient, and must never raise."""
    result = evaluate_failover(
        UNGOVERNED_APP,
        policies={},
        unavailable_workload_ids={UNGOVERNED_APP},
    )

    assert result.outcome is FailoverOutcome.UNGOVERNED
    assert result.selected_target_workload_id is None
    assert result.outcome is not FailoverOutcome.PRIMARY_HEALTHY


def test_estate_evaluation_never_skips_an_ungoverned_workload() -> None:
    """Deliberate-break: a workload with no declared policy must still
    appear in a full-estate evaluation run, reported ungoverned -- not
    silently dropped because it has nothing to look up."""
    primary_az = PRIMARY_DB + "-az1"
    policy = FailoverPolicy(
        workload_id=PRIMARY_DB,
        primary_target_workload_id=primary_az,
        secondary_target_workload_id=SECONDARY_DB,
    )
    policies = {PRIMARY_DB: policy}

    workloads = [_workload(PRIMARY_DB), _workload(UNGOVERNED_APP)]

    results = evaluate_estate_failover(workloads, policies, unavailable_workload_ids=set())

    assert len(results) == len(workloads)
    by_workload = {r.workload_id: r for r in results}
    assert by_workload[PRIMARY_DB].outcome is FailoverOutcome.PRIMARY_HEALTHY
    assert by_workload[UNGOVERNED_APP].outcome is FailoverOutcome.UNGOVERNED


def test_estate_evaluation_is_stably_ordered_by_workload_id() -> None:
    workloads = [_workload(TERTIARY_DB), _workload(PRIMARY_DB), _workload(SECONDARY_DB)]

    results = evaluate_estate_failover(workloads, policies={}, unavailable_workload_ids=set())

    assert [r.workload_id for r in results] == sorted(w.workload_id for w in workloads)


def test_policy_rejects_primary_target_equal_to_protected_workload() -> None:
    with pytest.raises(ValidationError):
        FailoverPolicy(workload_id=PRIMARY_DB, primary_target_workload_id=PRIMARY_DB)


def test_policy_rejects_secondary_target_equal_to_protected_workload() -> None:
    with pytest.raises(ValidationError):
        FailoverPolicy(
            workload_id=PRIMARY_DB,
            primary_target_workload_id=PRIMARY_DB + "-az1",
            secondary_target_workload_id=PRIMARY_DB,
        )


def test_policy_rejects_secondary_target_equal_to_primary_target() -> None:
    with pytest.raises(ValidationError):
        FailoverPolicy(
            workload_id=PRIMARY_DB,
            primary_target_workload_id=SECONDARY_DB,
            secondary_target_workload_id=SECONDARY_DB,
        )
