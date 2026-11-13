"""CAIRN cairn_modules.ingestion: R1-03 file ingestion adapters.

One adapter per supported source file format (CSV, JSON, RVTools vInfo
export, HVTools export, CycloneDX BOM). Each adapter parses a source file's
text content into an ``IngestionResult`` of ``RawObservation`` records --
the file's own fields, unnormalized -- and stamps every observation with
the parser version that produced it. Normalizing these into the canonical
estate model is R1-06, out of scope here.
"""

from cairn_modules.ingestion import (
    bom_adapter,
    csv_adapter,
    hvtools_adapter,
    json_adapter,
    rvtools_adapter,
)
from cairn_modules.ingestion.models import IngestionResult, RawObservation

__all__ = [
    "IngestionResult",
    "RawObservation",
    "bom_adapter",
    "csv_adapter",
    "hvtools_adapter",
    "json_adapter",
    "rvtools_adapter",
]
