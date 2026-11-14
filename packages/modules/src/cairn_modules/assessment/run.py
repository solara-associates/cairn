"""R1-15: assessment run state machine, checkpoints and errors.

Sequences a project's assessment into six ordered stages -- ingestion
(R1-04), estate normalization and workload derivation (R1-06/R1-07),
posture (R1-09/R1-10), cost (R1-11/R1-12), TCO (R1-13), 6R
classification (R1-14) -- as one resumable run, following R1-04's own
checkpoint/resume pattern as the model (``RunState``, transition table,
``CheckpointStore`` port, checkpoint-after-every-step).

Unlike R1-04's batch of independent files (one file's failure is just a
coverage gap; every other file still proceeds), these stages are
strictly sequential: each one's input is the previous one's output.
A failed stage must never be skipped, so a stage raising does **not**
advance the run past it -- the run is left ``CHECKPOINTED`` with that
same stage still ``pending``, and calling :func:`advance_run` again
retries exactly that stage, nothing ahead of it. ``FAILED`` is reserved
for the checkpoint store itself breaking (A5.10), exactly as in R1-04 --
a stage's own exception never reaches it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from cairn_kernel.errors import InvalidStateTransitionError, NotFoundError

from cairn_modules.ingestion.run import RunState, validate_run_transition

#: Fixed stage order. A run's ``stages`` field is always exactly this,
#: decided at queue time -- see :func:`queue_run`.
STAGES: tuple[str, ...] = ("ingestion", "estate", "posture", "cost", "tco", "classification")


@dataclass(frozen=True, slots=True)
class AssessmentContext:
    """The accumulated output of every stage that has completed so far.

    ``artifacts`` is keyed by stage name (e.g. ``"workloads"``,
    ``"cost_baseline"``) so a later stage reads exactly what an earlier
    one produced, by name, rather than by position.
    """

    tenant_id: str
    project_id: str
    artifacts: Mapping[str, Any] = field(default_factory=dict)

    def with_artifact(self, name: str, value: Any) -> AssessmentContext:
        return replace(self, artifacts={**self.artifacts, name: value})


Stage = Callable[[AssessmentContext], AssessmentContext]


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One stage's outcome within a run: completed, or failed and retryable."""

    stage: str
    succeeded: bool
    error: str | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AssessmentRun:
    """A single assessment run's durable checkpoint record."""

    run_id: str
    tenant_id: str
    project_id: str
    stages: tuple[str, ...]
    state: RunState
    context: AssessmentContext
    completed_stages: tuple[str, ...] = ()
    outcomes: tuple[StageOutcome, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def pending_stages(self) -> tuple[str, ...]:
        done = set(self.completed_stages)
        return tuple(stage for stage in self.stages if stage not in done)

    @property
    def failed_outcomes(self) -> tuple[StageOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.succeeded)

    @property
    def coverage(self) -> float:
        if not self.stages:
            return 0.0
        return len(self.completed_stages) / len(self.stages)


class CheckpointStore(Protocol):
    """Port for durable ``AssessmentRun`` storage (A5.10)."""

    def save(self, run: AssessmentRun) -> None: ...

    def load(self, run_id: str) -> AssessmentRun: ...


class InMemoryCheckpointStore:
    """Reference ``CheckpointStore`` adapter: a dict keyed by ``run_id``."""

    def __init__(self) -> None:
        self._runs: dict[str, AssessmentRun] = {}

    def save(self, run: AssessmentRun) -> None:
        self._runs[run.run_id] = run

    def load(self, run_id: str) -> AssessmentRun:
        try:
            return self._runs[run_id]
        except KeyError:
            raise NotFoundError(f"assessment run {run_id} not found") from None


def queue_run(
    store: CheckpointStore,
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    stages: tuple[str, ...] = STAGES,
) -> AssessmentRun:
    """Create and persist a new run in ``QUEUED`` state."""

    run = AssessmentRun(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        stages=stages,
        state=RunState.QUEUED,
        context=AssessmentContext(tenant_id=tenant_id, project_id=project_id),
    )
    store.save(run)
    return run


def advance_run(
    store: CheckpointStore,
    run_id: str,
    *,
    stage_fns: Mapping[str, Stage],
) -> AssessmentRun:
    """Advance a run as far as it will go, checkpointing after every stage.

    Safe to call on a fresh ``QUEUED`` run or a ``CHECKPOINTED`` run left
    behind by a crash, or by a prior stage's failure: in both cases it
    resumes from ``pending_stages``, so a stage already in
    ``completed_stages`` is never re-run.

    A stage whose callable raises is recorded as a failed
    :class:`StageOutcome` and the run stops there, still
    ``CHECKPOINTED`` with that stage still pending -- it is not skipped.
    The caller (typically after fixing whatever the stage's exception
    named) calls this again with the same ``run_id`` to retry it.
    """

    run = store.load(run_id)
    if run.state not in (RunState.QUEUED, RunState.CHECKPOINTED):
        raise InvalidStateTransitionError(
            f"assessment run {run_id} is {run.state.value}, not resumable"
        )

    validate_run_transition(run.state, RunState.RUNNING)
    run = replace(run, state=RunState.RUNNING, updated_at=datetime.now(UTC))
    store.save(run)

    for stage in run.pending_stages:
        stage_fn = stage_fns[stage]
        try:
            context = stage_fn(run.context)
        except Exception as exc:  # noqa: BLE001 - recorded, run stays resumable at this stage
            outcome = StageOutcome(stage=stage, succeeded=False, error=str(exc))
            run = replace(
                run,
                outcomes=(*run.outcomes, outcome),
                state=RunState.CHECKPOINTED,
                updated_at=datetime.now(UTC),
            )
            store.save(run)
            return run

        outcome = StageOutcome(stage=stage, succeeded=True, completed_at=datetime.now(UTC))
        run = replace(
            run,
            context=context,
            completed_stages=(*run.completed_stages, stage),
            outcomes=(*run.outcomes, outcome),
            state=RunState.CHECKPOINTED,
            updated_at=datetime.now(UTC),
        )
        # Checkpoint after every stage: this save is what makes a crash on
        # the *next* stage resumable from here rather than from the start.
        store.save(run)

    final_state = RunState.COMPLETED
    validate_run_transition(run.state, final_state)
    run = replace(run, state=final_state, updated_at=datetime.now(UTC))
    store.save(run)
    return run


def coverage_report(run: AssessmentRun) -> Mapping[str, object]:
    """A queryable summary of a run's coverage, including any failure."""

    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "total_stages": len(run.stages),
        "completed_stages": list(run.completed_stages),
        "pending_stages": list(run.pending_stages),
        "coverage": run.coverage,
        "failures": tuple(
            {"stage": outcome.stage, "error": outcome.error} for outcome in run.failed_outcomes
        ),
    }


__all__ = [
    "STAGES",
    "AssessmentContext",
    "AssessmentRun",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "RunState",
    "Stage",
    "StageOutcome",
    "advance_run",
    "coverage_report",
    "queue_run",
]
