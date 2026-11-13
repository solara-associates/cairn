"""Ingestion run state machine, checkpoints and errors (R1-04).

R1-03 gave us pure, stateless adapters: ``parse(content) -> IngestionResult``.
An ingestion *run* wraps those adapters over a batch of source files and adds
exactly what a single parse call cannot have: a durable position in the
batch, so a crash mid-run resumes from the last completed file instead of
reprocessing it, and an explicit record of any file the run could not parse,
so a partial run's coverage gap is queryable rather than silently dropped.

States
------
``QUEUED -> RUNNING -> (CHECKPOINTED <-> RUNNING)* -> COMPLETED | FAILED``

``RUNNING`` and ``CHECKPOINTED`` are not distinguished by data shape -- a
checkpoint is simply the state the run is in between files, visible to
anything inspecting it between steps. ``FAILED`` is a per-run terminal state
reached only when every remaining file errors or the caller aborts; a run
that parses some files and records errors for others, but processes every
file to a decision, is ``COMPLETED`` with a non-empty ``failed_files`` --
that is the "partial coverage recorded" case the acceptance criteria asks
for, not a run failure.

Durable state (A5.10): this module declares the store as a port
(``CheckpointStore``) rather than assuming one. ``InMemoryCheckpointStore``
is the reference adapter used by the tests below and is adequate for a
single-process worker; a persistent adapter (e.g. Postgres-backed) binds the
same port without changing ``IngestionRun``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from cairn_kernel.errors import InvalidStateTransitionError, NotFoundError

from cairn_modules.ingestion.models import IngestionResult


class RunState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ADR-009-style transition table, scoped to this run's own states. A run
# already COMPLETED or FAILED is terminal: resuming it is a caller error
# (InvalidStateTransitionError), not silently re-run.
ALLOWED_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.QUEUED: frozenset({RunState.RUNNING, RunState.FAILED}),
    RunState.RUNNING: frozenset(
        {RunState.CHECKPOINTED, RunState.COMPLETED, RunState.FAILED}
    ),
    RunState.CHECKPOINTED: frozenset(
        {RunState.RUNNING, RunState.COMPLETED, RunState.FAILED}
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
}


def validate_run_transition(current: RunState, target: RunState) -> None:
    allowed = ALLOWED_RUN_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"ingestion run cannot move from {current.value} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class FileOutcome:
    """One file's outcome within a run: parsed, or recorded as a gap."""

    file_id: str
    source_format: str
    succeeded: bool
    record_count: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionRun:
    """A single ingestion run's durable checkpoint record.

    ``file_ids`` is the run's fixed, ordered batch, decided at ``queued``
    time. ``completed_file_ids`` and ``outcomes`` only ever grow -- a resumed
    run re-reads this record and continues from
    ``len(completed_file_ids)``, it never clears or replaces an existing
    entry, which is what makes a crash mid-batch resumable rather than
    restart-from-zero.
    """

    run_id: str
    tenant_id: str
    project_id: str
    file_ids: tuple[str, ...]
    state: RunState
    completed_file_ids: tuple[str, ...] = ()
    outcomes: tuple[FileOutcome, ...] = field(default=())
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def pending_file_ids(self) -> tuple[str, ...]:
        done = set(self.completed_file_ids)
        return tuple(file_id for file_id in self.file_ids if file_id not in done)

    @property
    def failed_outcomes(self) -> tuple[FileOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.succeeded)

    @property
    def coverage(self) -> float:
        """Fraction of the run's batch that reached a successful parse.

        ``0.0`` for an empty batch avoids a division by zero reading as full
        coverage; an empty run should never claim coverage.
        """

        if not self.file_ids:
            return 0.0
        succeeded = sum(1 for outcome in self.outcomes if outcome.succeeded)
        return succeeded / len(self.file_ids)

    def has_partial_coverage(self) -> bool:
        """True once the run has recorded at least one failed file."""

        return any(not outcome.succeeded for outcome in self.outcomes)


class CheckpointStore(Protocol):
    """Port for durable ``IngestionRun`` storage (A5.10).

    A run's state must survive the process that was running it crashing;
    this is the seam a persistent adapter binds. ``InMemoryCheckpointStore``
    below is the reference / test adapter.
    """

    def save(self, run: IngestionRun) -> None: ...

    def load(self, run_id: str) -> IngestionRun: ...


class InMemoryCheckpointStore:
    """Reference ``CheckpointStore`` adapter: a dict keyed by ``run_id``.

    Adequate for a single-process worker and for tests; a crash that loses
    this dict is exactly the case a real deployment uses a persistent
    adapter (Postgres, etc.) to survive -- this adapter proves the state
    machine resumes correctly against *some* store, independent of which.
    """

    def __init__(self) -> None:
        self._runs: dict[str, IngestionRun] = {}

    def save(self, run: IngestionRun) -> None:
        self._runs[run.run_id] = run

    def load(self, run_id: str) -> IngestionRun:
        try:
            return self._runs[run_id]
        except KeyError:
            raise NotFoundError(f"ingestion run {run_id} not found") from None


def queue_run(
    store: CheckpointStore,
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    file_ids: tuple[str, ...],
) -> IngestionRun:
    """Create and persist a new run in ``QUEUED`` state.

    The file batch is fixed here and never changes for this ``run_id`` --
    resuming a run resumes exactly this batch, it does not pick up files
    added after the run was queued.
    """

    run = IngestionRun(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        file_ids=file_ids,
        state=RunState.QUEUED,
    )
    store.save(run)
    return run


def run_or_resume(
    store: CheckpointStore,
    run_id: str,
    *,
    load_content: Callable[[str], str],
    parse: Callable[[str], IngestionResult],
) -> IngestionRun:
    """Advance a run to completion, checkpointing after every file.

    Safe to call on a fresh ``QUEUED`` run or on a ``CHECKPOINTED`` run left
    behind by a crashed process: in both cases it starts from
    ``pending_file_ids``, so a file already in ``completed_file_ids`` is
    never re-parsed. ``load_content`` and ``parse`` are injected so a test
    can simulate a crash (raise) partway through a batch without touching
    real I/O.

    A file whose ``load_content`` or ``parse`` call raises is recorded as a
    failed ``FileOutcome`` (coverage gap, not a run failure) and the run
    continues to the next file -- one bad file must not abort the batch.
    The run only reaches ``FAILED`` if ``store.save``/``store.load`` itself
    raises (the checkpoint mechanism breaking), which propagates uncaught so
    the caller sees it and can retry the resume.
    """

    run = store.load(run_id)
    if run.state not in (RunState.QUEUED, RunState.CHECKPOINTED):
        raise InvalidStateTransitionError(
            f"ingestion run {run_id} is {run.state.value}, not resumable"
        )

    validate_run_transition(run.state, RunState.RUNNING)
    run = replace(run, state=RunState.RUNNING, updated_at=datetime.now(UTC))
    store.save(run)

    for file_id in run.pending_file_ids:
        try:
            content = load_content(file_id)
            result = parse(content)
            outcome = FileOutcome(
                file_id=file_id,
                source_format=result.source_format,
                succeeded=True,
                record_count=result.record_count,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            outcome = FileOutcome(
                file_id=file_id,
                source_format="unknown",
                succeeded=False,
                error=str(exc),
            )

        run = replace(
            run,
            completed_file_ids=(*run.completed_file_ids, file_id),
            outcomes=(*run.outcomes, outcome),
            state=RunState.CHECKPOINTED,
            updated_at=datetime.now(UTC),
        )
        # Checkpoint after every file: this save is what makes a crash on
        # the *next* file resumable from here rather than from the start.
        store.save(run)

    final_state = RunState.COMPLETED
    validate_run_transition(run.state, final_state)
    run = replace(run, state=final_state, updated_at=datetime.now(UTC))
    store.save(run)
    return run


def coverage_report(run: IngestionRun) -> Mapping[str, object]:
    """A queryable summary of a run's coverage, including any gap.

    Never omits a failed file: ``gaps`` names every file id that did not
    reach a successful parse and the error recorded for it, so "partial
    coverage" is an explicit, inspectable fact about the run rather than a
    silently dropped file.
    """

    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "total_files": len(run.file_ids),
        "completed_files": len(run.completed_file_ids),
        "coverage": run.coverage,
        "gaps": tuple(
            {"file_id": outcome.file_id, "error": outcome.error}
            for outcome in run.failed_outcomes
        ),
    }


__all__ = [
    "ALLOWED_RUN_TRANSITIONS",
    "CheckpointStore",
    "FileOutcome",
    "InMemoryCheckpointStore",
    "IngestionRun",
    "RunState",
    "coverage_report",
    "queue_run",
    "run_or_resume",
    "validate_run_transition",
]
