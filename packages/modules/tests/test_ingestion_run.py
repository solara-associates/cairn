"""Tests for the R1-04 ingestion run state machine, checkpoints and errors.

Two acceptance scenarios, per the spec row (section 16.0, R1-04):
"Resumable after failure; partial coverage recorded."

- resume-after-crash: a simulated crash mid-batch, a fresh resume call
  against the same checkpoint store, and a count of how many times each
  file was actually parsed -- a correct resume parses the crashed-on file
  once more and every already-completed file zero more times.
- partial-failure: a run that completes with some files unparseable records
  an explicit, queryable coverage gap rather than silently dropping them.
"""

from __future__ import annotations

import pytest
from cairn_kernel.errors import InvalidStateTransitionError, NotFoundError
from cairn_modules.ingestion import csv_adapter
from cairn_modules.ingestion.run import (
    InMemoryCheckpointStore,
    RunState,
    coverage_report,
    queue_run,
    run_or_resume,
    validate_run_transition,
)

GOLDEN_CSV = "hostname,role\nweb-01,web\ndb-01,db\n"
BROKEN_CSV = "not,a,valid\nfile"  # mismatched column count -> ValidationError


# --- state machine shape -----------------------------------------------------


def test_allowed_transitions_reject_resuming_a_terminal_run() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunState.COMPLETED, RunState.RUNNING)
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunState.FAILED, RunState.RUNNING)


def test_queue_run_starts_in_queued_state() -> None:
    store = InMemoryCheckpointStore()
    run = queue_run(
        store,
        run_id="run-1",
        tenant_id="t1",
        project_id="p1",
        file_ids=("f1", "f2"),
    )
    assert run.state is RunState.QUEUED
    assert run.pending_file_ids == ("f1", "f2")
    assert store.load("run-1") == run


def test_load_missing_run_raises_not_found() -> None:
    store = InMemoryCheckpointStore()
    with pytest.raises(NotFoundError):
        store.load("does-not-exist")


def test_resume_on_terminal_run_is_rejected() -> None:
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-1", tenant_id="t1", project_id="p1", file_ids=("f1",))
    run_or_resume(
        store,
        "run-1",
        load_content=lambda _file_id: GOLDEN_CSV,
        parse=csv_adapter.parse,
    )
    with pytest.raises(InvalidStateTransitionError):
        run_or_resume(
            store,
            "run-1",
            load_content=lambda _file_id: GOLDEN_CSV,
            parse=csv_adapter.parse,
        )


# --- resume after crash -------------------------------------------------------


def test_resume_after_crash_does_not_reprocess_completed_files() -> None:
    """Kill the run mid-batch, restart it, and confirm it resumes from the
    checkpoint rather than restarting -- each file is parsed exactly once
    across the crash and the resume, never twice."""

    store = InMemoryCheckpointStore()
    queue_run(
        store,
        run_id="run-crash",
        tenant_id="t1",
        project_id="p1",
        file_ids=("f1", "f2", "f3"),
    )

    parse_calls: list[str] = []

    # First attempt: f1 checkpoints fine, f2 "crashes" the host process --
    # here, simulated by the loader raising an exception that escapes the
    # run_or_resume call entirely (not caught internally), standing in for
    # a hard process kill where no FileOutcome for f2 is ever recorded.
    def crashing_load_content_hard(file_id: str) -> str:
        parse_calls.append(file_id)
        if file_id == "f2":
            raise SystemExit("simulated hard crash")
        return GOLDEN_CSV

    with pytest.raises(SystemExit):
        run_or_resume(
            store,
            "run-crash",
            load_content=crashing_load_content_hard,
            parse=csv_adapter.parse,
        )

    crashed_run = store.load("run-crash")
    assert crashed_run.state is RunState.CHECKPOINTED
    assert crashed_run.completed_file_ids == ("f1",)
    assert parse_calls == ["f1", "f2"]

    # Restart: a fresh call against the same store, same run_id.
    parse_calls.clear()
    resumed = run_or_resume(
        store,
        "run-crash",
        load_content=lambda file_id: (parse_calls.append(file_id), GOLDEN_CSV)[1],
        parse=csv_adapter.parse,
    )

    assert resumed.state is RunState.COMPLETED
    assert resumed.completed_file_ids == ("f1", "f2", "f3")
    # f1 was never touched again; only the pending files were (re-)loaded.
    assert parse_calls == ["f2", "f3"]
    assert len(resumed.outcomes) == 3
    assert all(outcome.succeeded for outcome in resumed.outcomes)


def test_resume_is_idempotent_on_already_completed_files() -> None:
    """A file already in completed_file_ids is never handed to load_content
    again, even across multiple resume calls."""

    store = InMemoryCheckpointStore()
    queue_run(
        store, run_id="run-multi", tenant_id="t1", project_id="p1", file_ids=("f1",)
    )
    run_or_resume(
        store, "run-multi", load_content=lambda _fid: GOLDEN_CSV, parse=csv_adapter.parse
    )
    completed = store.load("run-multi")
    assert completed.state is RunState.COMPLETED
    assert completed.pending_file_ids == ()


# --- partial failure / coverage ----------------------------------------------


def test_partial_failure_completes_run_and_records_coverage_gap() -> None:
    """A run with one unparseable file among several still reaches
    COMPLETED (one bad file does not abort the batch), and the gap is
    explicit and queryable, not dropped."""

    store = InMemoryCheckpointStore()
    queue_run(
        store,
        run_id="run-partial",
        tenant_id="t1",
        project_id="p1",
        file_ids=("good-1", "bad-1", "good-2"),
    )

    contents = {"good-1": GOLDEN_CSV, "bad-1": BROKEN_CSV, "good-2": GOLDEN_CSV}
    result = run_or_resume(
        store,
        "run-partial",
        load_content=lambda file_id: contents[file_id],
        parse=csv_adapter.parse,
    )

    assert result.state is RunState.COMPLETED
    assert result.has_partial_coverage() is True
    assert result.coverage == pytest.approx(2 / 3)

    report = coverage_report(result)
    assert report["state"] == "COMPLETED"
    assert report["total_files"] == 3
    assert report["completed_files"] == 3
    assert report["coverage"] == pytest.approx(2 / 3)
    gaps = report["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["file_id"] == "bad-1"
    assert gaps[0]["error"]  # a non-empty, queryable error message


def test_full_failure_still_records_every_gap() -> None:
    store = InMemoryCheckpointStore()
    queue_run(
        store,
        run_id="run-all-bad",
        tenant_id="t1",
        project_id="p1",
        file_ids=("bad-1", "bad-2"),
    )
    result = run_or_resume(
        store,
        "run-all-bad",
        load_content=lambda _fid: BROKEN_CSV,
        parse=csv_adapter.parse,
    )
    assert result.state is RunState.COMPLETED
    assert result.coverage == 0.0
    assert len(result.failed_outcomes) == 2


def test_empty_batch_has_zero_coverage_not_full_coverage() -> None:
    store = InMemoryCheckpointStore()
    queue_run(store, run_id="run-empty", tenant_id="t1", project_id="p1", file_ids=())
    result = run_or_resume(
        store, "run-empty", load_content=lambda _fid: GOLDEN_CSV, parse=csv_adapter.parse
    )
    assert result.state is RunState.COMPLETED
    assert result.coverage == 0.0
    assert result.has_partial_coverage() is False
