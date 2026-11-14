"""CAIRN cairn_modules.assessment: R1-15 assessment orchestration.

Sequences ingestion (R1-04) -> estate normalization and workload
derivation (R1-06/R1-07) -> posture (R1-09/R1-10) -> cost (R1-11/R1-12)
-> TCO (R1-13) -> 6R classification (R1-14) for one project, as one
resumable run, publishing every stage transition through R1-23's real
transactional outbox.
"""

from cairn_modules.assessment.outbox import OutboxPublishingCheckpointStore
from cairn_modules.assessment.run import (
    STAGES,
    AssessmentContext,
    AssessmentRun,
    CheckpointStore,
    InMemoryCheckpointStore,
    RunState,
    Stage,
    StageOutcome,
    advance_run,
    coverage_report,
    queue_run,
)
from cairn_modules.assessment.service import AssessmentService
from cairn_modules.assessment.stages import build_real_stages

__all__ = [
    "STAGES",
    "AssessmentContext",
    "AssessmentRun",
    "AssessmentService",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "OutboxPublishingCheckpointStore",
    "RunState",
    "Stage",
    "StageOutcome",
    "advance_run",
    "build_real_stages",
    "coverage_report",
    "queue_run",
]
