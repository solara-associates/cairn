"""CAIRN cairn_modules.ingestion: R1-03 file ingestion adapters and the
R1-04 ingestion run state machine.

One adapter per supported source file format (CSV, JSON, RVTools vInfo
export, HVTools export, CycloneDX BOM). Each adapter parses a source file's
text content into an ``IngestionResult`` of ``RawObservation`` records --
the file's own fields, unnormalized -- and stamps every observation with
the parser version that produced it. Normalizing these into the canonical
estate model is R1-06, out of scope here.

``run`` wraps these adapters in a resumable, checkpointed run over a batch
of files, recording any file that fails to parse as explicit partial
coverage rather than dropping it.
"""

from cairn_modules.ingestion import (
    bom_adapter,
    csv_adapter,
    hvtools_adapter,
    json_adapter,
    run,
    rvtools_adapter,
)
from cairn_modules.ingestion.models import IngestionResult, RawObservation
from cairn_modules.ingestion.run import (
    CheckpointStore,
    FileOutcome,
    IngestionRun,
    InMemoryCheckpointStore,
    RunState,
)

__all__ = [
    "CheckpointStore",
    "FileOutcome",
    "InMemoryCheckpointStore",
    "IngestionResult",
    "IngestionRun",
    "RawObservation",
    "RunState",
    "bom_adapter",
    "csv_adapter",
    "hvtools_adapter",
    "json_adapter",
    "run",
    "rvtools_adapter",
]
