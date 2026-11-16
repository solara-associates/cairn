"""Tests for R2-06: migration roadmap and wave sequencing.

Covers the acceptance criterion: "Dependencies respected; constraints and
risks shown" (spec §16's R2-06 row).

- dependency-respecting ordering: a workload is never placed in a wave
  before something it depends on, including a cyclic case that must fail
  closed with ``DependencyCycleError``, not an infinite loop or a silently
  dropped workload;
- constraints/risks surfaced: a workload blocked by an unresolved mapping
  or a still-pending disposition decision is visible in the roadmap
  output with an explicit constraint, never just quietly placed in a
  wave;
- revision immutability/monotonicity against ``subject_revision``,
  ``subject_kind="plan"`` -- the same test pattern R2-04 used for
  ``subject_kind="design"``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_contracts.estate import (
    DecisionStatus,
    Dependency,
    DependencyDirection,
    DependencyKind,
    Disposition,
    DispositionDecision,
    FactStatus,
    Workload,
)
from cairn_kernel.errors import DependencyCycleError, ValidationError
from cairn_kernel.hex import TenantId
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.approvals.model import RevisionRecord
from cairn_modules.design.target_model import TargetModel, TargetResourceEntry, TargetResourceStatus
from cairn_modules.planning import (
    PLAN_SUBJECT_KIND,
    FakePlanRevisionRepository,
    RoadmapConstraintKind,
    generate_roadmap,
)

TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
PLAN_ID = "33333333-3333-3333-3333-333333333333"


def _workload(workload_id: str, *, resource_ids: tuple[str, ...] = ()) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        name=workload_id,
        environment="UNVERIFIED",
        owner=None,
        business_context=None,
        resource_ids=resource_ids,
        dependency_ids=(),
        facts={},
        disposition=None,
        disposition_confidence=None,
        model_version="r1-07-grouping-v1",
        mapping_version="r1-07-grouping-v1",
    )


def _dependency(
    source: str,
    target: str,
    *,
    direction: DependencyDirection = DependencyDirection.ONE_WAY,
) -> Dependency:
    return Dependency(
        dependency_id=f"dep-{source}-{target}",
        tenant_id=TENANT,
        project_id=PROJECT,
        source_workload_id=source,
        target_workload_id=target,
        kind=DependencyKind.NETWORK,
        direction=direction,
        status=FactStatus.OBSERVED,
        provenance=(),
    )


def _decision(workload_id: str, *, status: DecisionStatus, disposition: Disposition = Disposition.REHOST) -> DispositionDecision:
    decided = status is not DecisionStatus.PROPOSED
    return DispositionDecision(
        decision_id=f"decision-{workload_id}",
        tenant_id=TENANT,
        project_id=PROJECT,
        workload_id=workload_id,
        disposition=disposition,
        rationale="test rationale",
        confidence=0.5,
        status=status,
        decided_by="alice" if decided else None,
        decided_at=datetime(2026, 11, 14, tzinfo=UTC) if decided else None,
        model_version="r1-14-conservative-default-v1",
        mapping_version="r1-14-conservative-default-v1",
    )


def _accepted_dispositions(*workload_ids: str) -> dict[str, DispositionDecision]:
    return {wid: _decision(wid, status=DecisionStatus.ACCEPTED) for wid in workload_ids}


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(TENANT),
        project_id=None,
        actor_id="alice",
        actor_roles=(),
        correlation_id="corr-1",
    )


def _target_model(*, unresolved_resource_ids: tuple[str, ...] = ()) -> TargetModel:
    entries = []
    for resource_id in unresolved_resource_ids:
        entries.append(
            TargetResourceEntry(
                resource_id=resource_id,
                source_provider="aws",
                source_service="rds",
                status=TargetResourceStatus.UNRESOLVED,
                resolution=None,
                reason="no mapping entry for this source service",
            )
        )
    return TargetModel(
        tenant_id=TENANT,
        project_id=PROJECT,
        design_id="design-1",
        pattern_id="web-app",
        pattern_catalogue_version="2026.11.1",
        mapping_release_version="2026.11.1",
        target_provider="gcp",
        parameters=(),
        resources=tuple(entries),
    )


# --- dependency-respecting ordering ----------------------------------------


def test_workload_is_never_scheduled_before_what_it_depends_on() -> None:
    # "app" depends on "db" (app is source, db is target -- R1-07 semantics).
    app = _workload("app")
    db = _workload("db")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(app, db),
        dependencies=(_dependency("app", "db"),),
        dispositions=_accepted_dispositions("app", "db"),
    )
    wave_of = {wl.workload_id: wave.wave_number for wave in roadmap.waves for wl in wave.workloads}
    assert wave_of["db"] < wave_of["app"]


def test_independent_workloads_land_in_the_same_first_wave() -> None:
    a = _workload("a")
    b = _workload("b")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(a, b),
        dispositions=_accepted_dispositions("a", "b"),
    )
    assert len(roadmap.waves) == 1
    assert roadmap.waves[0].wave_number == 1
    assert {wl.workload_id for wl in roadmap.waves[0].workloads} == {"a", "b"}


def test_multi_level_chain_produces_one_wave_per_level() -> None:
    # c depends on b depends on a: a -> wave 1, b -> wave 2, c -> wave 3.
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("a"), _workload("b"), _workload("c")),
        dependencies=(_dependency("b", "a"), _dependency("c", "b")),
        dispositions=_accepted_dispositions("a", "b", "c"),
    )
    wave_of = {wl.workload_id: wave.wave_number for wave in roadmap.waves for wl in wave.workloads}
    assert wave_of == {"a": 1, "b": 2, "c": 3}
    assert [wave.wave_number for wave in roadmap.waves] == [1, 2, 3]


def test_every_workload_appears_exactly_once_across_waves() -> None:
    workloads = tuple(_workload(f"w{i}") for i in range(5))
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=workloads,
        dispositions=_accepted_dispositions(*(w.workload_id for w in workloads)),
    )
    all_ids = [wl.workload_id for wave in roadmap.waves for wl in wave.workloads]
    assert sorted(all_ids) == [f"w{i}" for i in range(5)]
    assert len(all_ids) == len(set(all_ids))


def test_direct_cycle_fails_closed_with_dependency_cycle_error() -> None:
    a = _workload("a")
    b = _workload("b")
    with pytest.raises(DependencyCycleError) as exc_info:
        generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            workloads=(a, b),
            dependencies=(_dependency("a", "b"), _dependency("b", "a")),
            dispositions=_accepted_dispositions("a", "b"),
        )
    assert "cyclic" in str(exc_info.value)
    assert "a" in str(exc_info.value)
    assert "b" in str(exc_info.value)


def test_bidirectional_dependency_between_two_workloads_is_a_cycle() -> None:
    a = _workload("a")
    b = _workload("b")
    with pytest.raises(DependencyCycleError):
        generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            workloads=(a, b),
            dependencies=(_dependency("a", "b", direction=DependencyDirection.BIDIRECTIONAL),),
            dispositions=_accepted_dispositions("a", "b"),
        )


def test_longer_cycle_also_fails_closed() -> None:
    # a -> b -> c -> a
    with pytest.raises(DependencyCycleError):
        generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            workloads=(_workload("a"), _workload("b"), _workload("c")),
            dependencies=(
                _dependency("a", "b"),
                _dependency("b", "c"),
                _dependency("c", "a"),
            ),
            dispositions=_accepted_dispositions("a", "b", "c"),
        )


def test_dependency_to_an_unknown_workload_is_ignored_not_fatal() -> None:
    a = _workload("a")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(a,),
        dependencies=(_dependency("a", "does-not-exist"),),
        dispositions=_accepted_dispositions("a"),
    )
    assert len(roadmap.waves) == 1
    assert roadmap.waves[0].workloads[0].workload_id == "a"


def _revision(
    *,
    tenant_id: str = TENANT,
    project_id: str = PROJECT,
    content_hash: str,
) -> RevisionRecord:
    return RevisionRecord(
        revision_id="99999999-9999-9999-9999-999999999999",
        tenant_id=tenant_id,
        project_id=project_id,
        subject_kind="design",
        subject_id="design-1",
        revision_number=1,
        content_hash=content_hash,
        input_versions=(),
        created_by="alice",
        created_at=datetime(2026, 11, 14, tzinfo=UTC),
    )


# --- revision/target-model consistency guard (720, mirroring 704/706) ------


def test_mismatched_revision_and_target_model_content_hash_raises_before_waves_are_computed() -> None:
    workload = _workload("app")
    target_model = _target_model()
    revision = _revision(content_hash="sha256:does-not-match")
    assert revision.content_hash != target_model.content_hash

    with pytest.raises(ValidationError) as exc_info:
        generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            # A workload whose dependency would be a cycle: if the guard
            # did not fire before wave computation, this would instead
            # raise DependencyCycleError, not ValidationError -- proving
            # the content-hash check happens first, not merely somewhere
            # before the function returns.
            workloads=(workload,),
            dependencies=(_dependency("app", "app"),),
            dispositions=_accepted_dispositions("app"),
            target_model=target_model,
            revision=revision,
        )
    assert "content_hash" in str(exc_info.value)


def test_revision_for_a_different_tenant_or_project_raises() -> None:
    target_model = _target_model()
    revision = _revision(
        project_id="99999999-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        content_hash=target_model.content_hash,
    )
    with pytest.raises(ValidationError) as exc_info:
        generate_roadmap(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN_ID,
            workloads=(_workload("app"),),
            dispositions=_accepted_dispositions("app"),
            target_model=target_model,
            revision=revision,
        )
    assert "tenant/project" in str(exc_info.value)


def test_matching_revision_and_target_model_raises_nothing() -> None:
    target_model = _target_model()
    revision = _revision(content_hash=target_model.content_hash)
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
        target_model=target_model,
        revision=revision,
    )
    assert roadmap.waves[0].workloads[0].workload_id == "app"


def test_revision_without_a_target_model_is_not_checked_and_behaves_as_before() -> None:
    # Passing only ``revision`` (no ``target_model``) is exactly today's
    # behaviour for every existing caller that doesn't pass a revision at
    # all -- the guard never fires with only one side present.
    revision = _revision(content_hash="sha256:anything-at-all")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
        revision=revision,
    )
    assert roadmap.waves[0].workloads[0].workload_id == "app"


# --- constraints and risks are surfaced, never silently swallowed ----------


def test_unresolved_mapping_blocks_a_workload_visibly() -> None:
    workload = _workload("app", resource_ids=("res-1",))
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions=_accepted_dispositions("app"),
        target_model=_target_model(unresolved_resource_ids=("res-1",)),
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert wave_workload.is_blocked
    assert any(c.kind is RoadmapConstraintKind.UNRESOLVED_MAPPING for c in wave_workload.constraints)
    assert "res-1" in wave_workload.constraints[0].detail
    assert "app" in roadmap.blocked_workload_ids


def test_pending_disposition_blocks_a_workload_visibly() -> None:
    workload = _workload("app")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions={"app": _decision("app", status=DecisionStatus.PROPOSED)},
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert wave_workload.is_blocked
    assert any(c.kind is RoadmapConstraintKind.PENDING_DISPOSITION for c in wave_workload.constraints)
    assert wave_workload.disposition is None
    assert "app" in roadmap.blocked_workload_ids


def test_missing_disposition_decision_is_also_a_pending_constraint() -> None:
    workload = _workload("app")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions={},
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert wave_workload.is_blocked
    assert any(c.kind is RoadmapConstraintKind.PENDING_DISPOSITION for c in wave_workload.constraints)


def test_accepted_disposition_and_resolved_mapping_produce_no_constraints() -> None:
    workload = _workload("app", resource_ids=("res-1",))
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions=_accepted_dispositions("app"),
        target_model=_target_model(),
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert not wave_workload.is_blocked
    assert wave_workload.constraints == ()
    assert wave_workload.disposition is Disposition.REHOST
    assert roadmap.blocked_workload_ids == ()


def test_amended_disposition_also_counts_as_resolved() -> None:
    workload = _workload("app")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions={
            "app": _decision("app", status=DecisionStatus.AMENDED, disposition=Disposition.RETIRE)
        },
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert not wave_workload.is_blocked
    assert wave_workload.disposition is Disposition.RETIRE


def test_rejected_disposition_is_surfaced_as_a_pending_constraint_not_scheduled_cleanly() -> None:
    workload = _workload("app")
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions={"app": _decision("app", status=DecisionStatus.REJECTED)},
    )
    wave_workload = roadmap.waves[0].workloads[0]
    assert wave_workload.is_blocked
    assert wave_workload.disposition is None


def test_blocked_workload_is_still_placed_in_its_dependency_respecting_wave() -> None:
    # "app" depends on "db"; db is unresolved. app must still be in a later
    # wave than db (dependency order is unaffected by blocking), and db's
    # block must still be visible.
    app = _workload("app", resource_ids=())
    db = _workload("db", resource_ids=("res-db",))
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(app, db),
        dependencies=(_dependency("app", "db"),),
        dispositions=_accepted_dispositions("app", "db"),
        target_model=_target_model(unresolved_resource_ids=("res-db",)),
    )
    wave_of = {wl.workload_id: wave.wave_number for wave in roadmap.waves for wl in wave.workloads}
    assert wave_of["db"] < wave_of["app"]
    by_id = {wl.workload_id: wl for wave in roadmap.waves for wl in wave.workloads}
    assert by_id["db"].is_blocked
    assert not by_id["app"].is_blocked


# --- determinism -------------------------------------------------------------


def test_same_inputs_produce_identical_content_hash() -> None:
    workload = _workload("app", resource_ids=("res-1",))
    kwargs = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "plan_id": PLAN_ID,
        "workloads": (workload,),
        "dispositions": _accepted_dispositions("app"),
        "target_model": _target_model(),
    }
    first = generate_roadmap(**kwargs)
    second = generate_roadmap(**kwargs)
    assert first.content_hash == second.content_hash
    assert first.content_hash != ""


def test_workload_input_order_does_not_affect_content_hash() -> None:
    a = _workload("a")
    b = _workload("b")
    forward = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(a, b),
        dispositions=_accepted_dispositions("a", "b"),
    )
    backward = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(b, a),
        dispositions=_accepted_dispositions("a", "b"),
    )
    assert forward.content_hash == backward.content_hash


# --- revision persistence: monotonic, append-only ---------------------------


def test_first_generation_is_revision_number_one() -> None:
    repo = FakePlanRevisionRepository()
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
    )
    with tenant_scope(_context()):
        record = repo.create_revision(plan_id=PLAN_ID, roadmap=roadmap, created_by="alice")
    assert record.revision_number == 1
    assert record.subject_kind == PLAN_SUBJECT_KIND
    assert record.subject_id == PLAN_ID
    assert record.content_hash == roadmap.content_hash


def test_regeneration_creates_revision_two_not_a_mutation() -> None:
    repo = FakePlanRevisionRepository()
    first_roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
    )
    second_roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"), _workload("db")),
        dependencies=(_dependency("app", "db"),),
        dispositions=_accepted_dispositions("app", "db"),
    )
    with tenant_scope(_context()):
        first = repo.create_revision(plan_id=PLAN_ID, roadmap=first_roadmap, created_by="alice")
        second = repo.create_revision(plan_id=PLAN_ID, roadmap=second_roadmap, created_by="alice")
        revisions = repo.list_revisions(tenant_id=TENANT, project_id=PROJECT, plan_id=PLAN_ID)

    assert second.revision_number == 2
    assert second.content_hash != first.content_hash
    assert [r.revision_number for r in revisions] == [1, 2]
    # the prior revision is still exactly as it was created -- never mutated.
    assert revisions[0].content_hash == first.content_hash
    assert revisions[0].revision_number == 1


def test_latest_revision_reflects_the_most_recent_generation() -> None:
    repo = FakePlanRevisionRepository()
    first_roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
    )
    second_roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"), _workload("db")),
        dispositions=_accepted_dispositions("app", "db"),
    )
    with tenant_scope(_context()):
        repo.create_revision(plan_id=PLAN_ID, roadmap=first_roadmap, created_by="alice")
        repo.create_revision(plan_id=PLAN_ID, roadmap=second_roadmap, created_by="alice")
        latest = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, plan_id=PLAN_ID)

    assert latest is not None
    assert latest.revision_number == 2
    assert latest.content_hash == second_roadmap.content_hash


def test_a_plan_with_no_revisions_yet_has_no_latest() -> None:
    repo = FakePlanRevisionRepository()
    with tenant_scope(_context()):
        assert repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, plan_id=PLAN_ID) is None


def test_revisions_for_distinct_plans_do_not_collide() -> None:
    repo = FakePlanRevisionRepository()
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(_workload("app"),),
        dispositions=_accepted_dispositions("app"),
    )
    with tenant_scope(_context()):
        repo.create_revision(plan_id="plan-a", roadmap=roadmap, created_by="alice")
        repo.create_revision(plan_id="plan-b", roadmap=roadmap, created_by="alice")
        a = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, plan_id="plan-a")
        b = repo.latest_revision(tenant_id=TENANT, project_id=PROJECT, plan_id="plan-b")
    assert a.revision_number == 1
    assert b.revision_number == 1


def test_revision_input_versions_carry_wave_and_blocked_counts() -> None:
    workload = _workload("app", resource_ids=("res-1",))
    roadmap = generate_roadmap(
        tenant_id=TENANT,
        project_id=PROJECT,
        plan_id=PLAN_ID,
        workloads=(workload,),
        dispositions={},
        target_model=_target_model(unresolved_resource_ids=("res-1",)),
    )
    repo = FakePlanRevisionRepository()
    with tenant_scope(_context()):
        record = repo.create_revision(plan_id=PLAN_ID, roadmap=roadmap, created_by="alice")
    input_versions = dict(record.input_versions)
    assert input_versions["wave_count"] == "1"
    assert input_versions["workload_count"] == "1"
    assert input_versions["blocked_workload_count"] == "1"
