"""CSV file ingestion adapter.

Parses a generic, header-row CSV export (any column set) into
``RawObservation`` records. Column names and values are taken verbatim from
the file; no type coercion or normalization happens here (that is R1-06).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from cairn_kernel.errors import ValidationError

from cairn_modules.ingestion.models import IngestionResult, RawObservation

SOURCE_FORMAT = "csv"
PARSER_VERSION = "csv-adapter-1.0.0"


def parse(content: str, *, observed_at: datetime | None = None) -> IngestionResult:
    """Parse a CSV document's text content into an ``IngestionResult``.

    Raises ``ValidationError`` for an empty file, a missing/empty header
    row, or a data row whose column count does not match the header.
    """
    moment = observed_at or datetime.now(UTC)
    if not content.strip():
        raise ValidationError("csv file is empty")

    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationError("csv file has no header row") from exc

    header = [column.strip() for column in header]
    if not header or any(column == "" for column in header):
        raise ValidationError("csv header row is missing or has an empty column name")
    if len(set(header)) != len(header):
        raise ValidationError("csv header row has duplicate column names")

    observations: list[RawObservation] = []
    for index, row in enumerate(reader):
        if len(row) != len(header):
            raise ValidationError(
                f"csv row {index} has {len(row)} columns, expected {len(header)}"
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


__all__ = ["PARSER_VERSION", "SOURCE_FORMAT", "parse"]
