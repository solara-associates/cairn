"""Raw-observation shape shared by every file ingestion adapter (R1-03).

ADR-003 reserves the canonical estate model for R1-06 normalization. These
adapters stop one step earlier: they turn a source file (CSV, JSON, an
RVTools export, an HVTools export, or a BOM document) into an ordered
sequence of ``RawObservation`` records -- the file's own fields, as strings,
with no cloud-provider typing and no attempt to reconcile conflicting
records. Every observation carries the parser version that produced it, so a
later re-parse with a changed adapter is distinguishable from the original.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RawObservation:
    """One parsed record from a source file, unnormalized.

    ``fields`` holds the record's own column/key names mapped to string
    values (or ``None`` for an explicitly empty value); adapters do not
    rename, retype, or drop fields the source file provided.
    """

    source_format: str
    parser_version: str
    record_index: int
    fields: Mapping[str, str | None]
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """The full output of parsing one source file."""

    source_format: str
    parser_version: str
    observations: tuple[RawObservation, ...]

    @property
    def record_count(self) -> int:
        return len(self.observations)


__all__ = ["IngestionResult", "RawObservation"]
