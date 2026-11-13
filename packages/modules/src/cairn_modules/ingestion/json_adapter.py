"""JSON file ingestion adapter.

Parses a generic JSON export -- either a top-level JSON array of objects,
or an object with a top-level ``"records"`` array -- into ``RawObservation``
records. Field names and values are taken verbatim; non-string scalar
values are stringified, nested objects/arrays are rejected as malformed
(this adapter ingests flat records only -- nested structure belongs to the
canonical model work in R1-06).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cairn_kernel.errors import ValidationError

from cairn_modules.ingestion.models import IngestionResult, RawObservation

SOURCE_FORMAT = "json"
PARSER_VERSION = "json-adapter-1.0.0"


def parse(content: str, *, observed_at: datetime | None = None) -> IngestionResult:
    """Parse a JSON document's text content into an ``IngestionResult``.

    Raises ``ValidationError`` for invalid JSON, a top-level shape that is
    neither an array nor an object with a ``"records"`` array, a non-object
    record, or a record field holding a nested object/array.
    """
    moment = observed_at or datetime.now(UTC)
    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"json file is not valid JSON: {exc}") from exc

    if isinstance(document, list):
        records = document
    elif isinstance(document, dict) and isinstance(document.get("records"), list):
        records = document["records"]
    else:
        raise ValidationError(
            "json file must be a top-level array or an object with a 'records' array"
        )

    observations: list[RawObservation] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValidationError(f"json record {index} is not an object")
        fields: dict[str, str | None] = {}
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                raise ValidationError(
                    f"json record {index} field '{key}' is nested; "
                    "only flat scalar fields are supported"
                )
            fields[key] = None if value is None else str(value)
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
