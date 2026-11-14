"""R1-15: worker-side entrypoint for advancing an assessment run.

``apps/worker`` has no job-queue/polling loop of its own yet -- adding
one is a separate, later decision (how jobs are claimed, retried,
scheduled), not this story's scope. This module is the real hook such
a loop would call: it wires a real ``cairn_modules.assessment.AssessmentService``
and advances one run by id, so the worker process (not just a test) can
genuinely drive a run to completion or resumption.
"""

from __future__ import annotations

from cairn_kernel.outbox import OutboxStore
from cairn_modules.assessment import AssessmentRun, AssessmentService, CheckpointStore, Stage


def advance_assessment_run(
    *,
    checkpoint_store: CheckpointStore,
    outbox: OutboxStore,
    run_id: str,
    stage_fns: dict[str, Stage],
) -> AssessmentRun:
    """Advance one assessment run, publishing its stage-transition events
    through ``outbox``. A thin wrapper so the worker process's own
    dependency wiring (which checkpoint store, which outbox adapter) is
    decided here, once, rather than scattered at every call site.
    """
    service = AssessmentService(checkpoint_store=checkpoint_store, outbox=outbox)
    return service.advance_run(run_id, stage_fns=stage_fns)


__all__ = ["advance_assessment_run"]
