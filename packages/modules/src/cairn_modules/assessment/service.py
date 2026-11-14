"""R1-15: the assessment orchestration service apps/api and apps/worker use.

Wires :mod:`cairn_modules.assessment.run`'s pure state machine to a real
``OutboxStore`` through :class:`OutboxPublishingCheckpointStore`, so
every stage transition this service drives publishes a real outbox
event -- never a direct ``EventPublisher`` call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from cairn_contracts.estate import DispositionDecision
from cairn_kernel.errors import NotFoundError
from cairn_kernel.outbox import OutboxStore

from cairn_modules.assessment.outbox import OutboxPublishingCheckpointStore
from cairn_modules.assessment.run import (
    STAGES,
    AssessmentRun,
    CheckpointStore,
    Stage,
    advance_run,
    coverage_report,
    queue_run,
)


class AssessmentService:
    """Queues and advances assessment runs for apps/api and apps/worker."""

    def __init__(
        self,
        *,
        checkpoint_store: CheckpointStore,
        outbox: OutboxStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = OutboxPublishingCheckpointStore(checkpoint_store, outbox=outbox, clock=clock)

    def queue_run(self, *, run_id: str, tenant_id: str, project_id: str) -> AssessmentRun:
        return queue_run(
            self._store, run_id=run_id, tenant_id=tenant_id, project_id=project_id, stages=STAGES
        )

    def advance_run(self, run_id: str, *, stage_fns: dict[str, Stage]) -> AssessmentRun:
        """Advance ``run_id`` using ``stage_fns`` -- supplied per call, since
        each run's stages are bound to that run's own inputs (the files it
        ingests, its billing batch, ...), not shared service-wide config.
        """
        return advance_run(self._store, run_id, stage_fns=stage_fns)

    def get_run(self, run_id: str) -> AssessmentRun:
        return self._store.load(run_id)

    def coverage_report(self, run_id: str) -> object:
        return coverage_report(self.get_run(run_id))

    def get_decision(self, run_id: str, decision_id: str) -> DispositionDecision:
        """The run's own R1-14 disposition decision with this id.

        Raises ``NotFoundError`` if the classification stage never ran,
        or ran but produced no decision with this id -- both are
        reported the same way the run itself is not-found elsewhere in
        this service, never a crash on a missing artifact key.
        """
        run = self.get_run(run_id)
        decisions: tuple[DispositionDecision, ...] = run.context.artifacts.get(
            "disposition_decisions", ()
        )
        for decision in decisions:
            if decision.decision_id == decision_id:
                return decision
        raise NotFoundError(f"disposition decision {decision_id} not found on run {run_id}")

    def review_decision(
        self, run_id: str, decision_id: str, reviewed: DispositionDecision
    ) -> AssessmentRun:
        """Persist ``reviewed`` (the output of an accept/amend/reject call
        in ``cairn_modules.planning``) back into the run's artifacts, and
        checkpoint the run so the review durably sticks and the usual
        stage-transition event still fires.
        """
        run = self.get_run(run_id)
        decisions: tuple[DispositionDecision, ...] = run.context.artifacts.get(
            "disposition_decisions", ()
        )
        updated = tuple(
            reviewed if decision.decision_id == decision_id else decision
            for decision in decisions
        )
        if updated == decisions and not any(
            decision.decision_id == decision_id for decision in decisions
        ):
            raise NotFoundError(f"disposition decision {decision_id} not found on run {run_id}")
        context = run.context.with_artifact("disposition_decisions", updated)
        run = replace(run, context=context, updated_at=datetime.now(UTC))
        self._store.save(run)
        return run


__all__ = ["AssessmentService"]
