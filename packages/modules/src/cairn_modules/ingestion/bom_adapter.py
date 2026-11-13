"""Bill of Materials (BOM) ingestion adapter.

Accepts a CycloneDX-shaped BOM document: a JSON object declaring
``"bomFormat": "CycloneDX"`` and a ``"components"`` array, each component
an object with at least a ``"name"``. Each component becomes one
``RawObservation``; nested component fields (e.g. ``"licenses"``) are kept
as their own flat sub-fields using a ``.`` path rather than being dropped,
since BOM components routinely carry one level of nested metadata.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cairn_kernel.errors import ValidationError

from cairn_modules.ingestion.models import IngestionResult, RawObservation

SOURCE_FORMAT = "bom"
PARSER_VERSION = "bom-adapter-1.0.0"


def _flatten(prefix: str, value: Any, out: dict[str, str | None]) -> None:
    if value is None:
        out[prefix] = None
    elif isinstance(value, dict):
        for key, nested in value.items():
            _flatten(f"{prefix}.{key}", nested, out)
    elif isinstance(value, list):
        for position, nested in enumerate(value):
            _flatten(f"{prefix}[{position}]", nested, out)
    else:
        out[prefix] = str(value)


def parse(content: str, *, observed_at: datetime | None = None) -> IngestionResult:
    """Parse a CycloneDX-shaped BOM document into an ``IngestionResult``.

    Raises ``ValidationError`` for invalid JSON, a document missing
    ``"bomFormat": "CycloneDX"``, a missing/non-list ``"components"``, a
    non-object component, or a component missing ``"name"``.
    """
    moment = observed_at or datetime.now(UTC)
    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"bom file is not valid JSON: {exc}") from exc

    if not isinstance(document, dict) or document.get("bomFormat") != "CycloneDX":
        raise ValidationError("bom file must be a CycloneDX document (bomFormat: 'CycloneDX')")

    components = document.get("components")
    if not isinstance(components, list):
        raise ValidationError("bom file must have a 'components' array")

    observations: list[RawObservation] = []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ValidationError(f"bom component {index} is not an object")
        if not component.get("name"):
            raise ValidationError(f"bom component {index} is missing 'name'")
        fields: dict[str, str | None] = {}
        for key, value in component.items():
            _flatten(key, value, fields)
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
