"""R1-15: publish assessment stage-transition events through R1-23's
real transactional outbox -- never a direct ``EventPublisher`` call that
bypasses it.

``OutboxPublishingCheckpointStore`` wraps a plain ``CheckpointStore`` so
every checkpoint save also enqueues a stage-transition event, atomically,
through ``OutboxStore.enqueue_with_effect``: either both the checkpoint
and the event are persisted, or neither is -- exactly the guarantee
R1-23 built and proved by failure injection. The pure orchestration loop
in ``cairn_modules.assessment.run`` never imports the outbox at all; it
just calls ``store.save(run)``, and this wrapper is what makes that save
also emit an event, by composition, not by changing the loop.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from cairn_kernel.outbox import OutboxMessage, OutboxStore

from cairn_modules.assessment.run import AssessmentRun, CheckpointStore


class OutboxPublishingCheckpointStore:
    """Decorates ``inner`` with outbox-backed stage-transition events."""

    def __init__(
        self,
        inner: CheckpointStore,
        *,
        outbox: OutboxStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._outbox = outbox
        self._clock = clock
        self._sequence: dict[str, int] = {}

    def load(self, run_id: str) -> AssessmentRun:
        return self._inner.load(run_id)

    def save(self, run: AssessmentRun) -> None:
        sequence = self._sequence.get(run.run_id, 0) + 1
        self._sequence[run.run_id] = sequence

        latest_outcome = run.outcomes[-1] if run.outcomes else None
        message = OutboxMessage(
            message_id=f"{run.run_id}:{sequence}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            event_type=f"assessment.run.{run.state.value.lower()}",
            payload={
                "run_id": run.run_id,
                "state": run.state.value,
                "completed_stages": list(run.completed_stages),
                "pending_stages": list(run.pending_stages),
                "latest_stage": latest_outcome.stage if latest_outcome else None,
                "latest_stage_succeeded": latest_outcome.succeeded if latest_outcome else None,
                "latest_stage_error": latest_outcome.error if latest_outcome else None,
            },
            created_at=self._clock(),
        )
        # Atomic with the checkpoint write: either both land, or neither
        # does (R1-23's own guarantee, not re-proved here).
        self._outbox.enqueue_with_effect(message, effect=lambda: self._inner.save(run))


__all__ = ["OutboxPublishingCheckpointStore"]
