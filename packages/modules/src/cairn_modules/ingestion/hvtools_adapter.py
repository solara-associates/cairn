"""HVTools export ingestion adapter.

HVTools-style exports are the Hyper-V equivalent of an RVTools vInfo
export: a CSV inventory of virtual machines with a fixed set of Hyper-V
specific columns. This adapter requires those columns so a file is
confirmed as an HVTools export rather than silently accepted as a
generic CSV.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from cairn_kernel.errors import ValidationError

from cairn_modules.ingestion.models import IngestionResult, RawObservation

SOURCE_FORMAT = "hvtools"
PARSER_VERSION = "hvtools-adapter-1.0.0"

#: Columns an HVTools VM inventory export always carries.
REQUIRED_COLUMNS = (
    "VMName",
    "State",
    "Generation",
    "CPUCount",
    "MemoryAssigned",
    "Host",
)


def parse(content: str, *, observed_at: datetime | None = None) -> IngestionResult:
    """Parse an HVTools VM inventory CSV export into an ``IngestionResult``.

    Raises ``ValidationError`` for an empty file, a missing header row, a
    header missing one of the mandatory HVTools columns, or a data row
    whose column count does not match the header.
    """
    moment = observed_at or datetime.now(UTC)
    if not content.strip():
        raise ValidationError("hvtools file is empty")

    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationError("hvtools file has no header row") from exc

    header = [column.strip() for column in header]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ValidationError(
            "hvtools file is missing required column(s): " + ", ".join(missing)
        )

    observations: list[RawObservation] = []
    for index, row in enumerate(reader):
        if len(row) != len(header):
            raise ValidationError(
                f"hvtools row {index} has {len(row)} columns, expected {len(header)}"
            )
        fields = {column: (value if value != "" else None) for column, value in zip(header, row)}
        observations.append(
            RawObservation(
                source_format=SOURCE_FORMAT,
                parser_version=PARSER_VERSION,
                record_index=index,
                fields=fields,
                observed_at=moment,
            )
        )

    return IngestionResult(
        source_format=SOURCE_FORMAT,
        parser_version=PARSER_VERSION,
        observations=tuple(observations),
    )


__all__ = ["PARSER_VERSION", "REQUIRED_COLUMNS", "SOURCE_FORMAT", "parse"]
