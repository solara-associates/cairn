"""R1-15: the assessment orchestration service apps/api and apps/worker use.

Wires :mod:`cairn_modules.assessment.run`'s pure state machine to a real
``OutboxStore`` through :class:`OutboxPublishingCheckpointStore`, so
every stage transition this service drives publishes a real outbox
event -- never a direct ``EventPublisher`` call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

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


__all__ = ["AssessmentService"]
