"""RVTools export ingestion adapter.

RVTools (a VMware vSphere inventory tool) exports its ``vInfo`` tab as a
CSV with a fixed set of VM-inventory columns. This adapter accepts that
CSV export and requires the columns that identify it as an RVTools vInfo
export; anything missing one of them is rejected as not an RVTools file,
rather than silently parsed as a generic CSV.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from cairn_kernel.errors import ValidationError

from cairn_modules.ingestion.models import IngestionResult, RawObservation

SOURCE_FORMAT = "rvtools"
PARSER_VERSION = "rvtools-adapter-1.0.0"

#: Columns RVTools always emits on the vInfo tab; used to confirm the file
#: is actually an RVTools export rather than an arbitrary CSV.
REQUIRED_COLUMNS = (
    "VM",
    "Powerstate",
    "CPUs",
    "Memory",
    "Datacenter",
    "Cluster",
    "Host",
)


def parse(content: str, *, observed_at: datetime | None = None) -> IngestionResult:
    """Parse an RVTools vInfo CSV export into an ``IngestionResult``.

    Raises ``ValidationError`` for an empty file, a missing header row, a
    header missing one of the mandatory RVTools vInfo columns, or a data
    row whose column count does not match the header.
    """
    moment = observed_at or datetime.now(UTC)
    if not content.strip():
        raise ValidationError("rvtools file is empty")

    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationError("rvtools file has no header row") from exc

    header = [column.strip() for column in header]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ValidationError(
            "rvtools file is missing required vInfo column(s): " + ", ".join(missing)
        )

    observations: list[RawObservation] = []
    for index, row in enumerate(reader):
        if len(row) != len(header):
            raise ValidationError(
                f"rvtools row {index} has {len(row)} columns, expected {len(header)}"
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
