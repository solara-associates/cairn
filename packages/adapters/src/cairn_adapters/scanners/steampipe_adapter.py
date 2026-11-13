"""Steampipe scanner adapter (R1-09).

Parses a Steampipe compliance benchmark run's native JSON output (a tree of
``group`` nodes, each with ``controls``, each control with a ``results``
array of per-resource rows) into a
:class:`~cairn_modules.posture.findings.ScanResult`. A control whose
``control_id`` is not mapped, or a result row with an unrecognized
``status``, is reported as an
:class:`~cairn_modules.posture.findings.UnsupportedRecord`, never dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cairn_kernel.errors import ValidationError
from cairn_modules.posture.findings import Finding, ScanResult, UnsupportedRecord
from cairn_modules.posture.normalization import UnsupportedRecordError, normalize_steampipe

SCANNER = "steampipe"
PARSER_VERSION = "steampipe-adapter-1.0.0"


def _iter_controls(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Depth-first collection of every ``control`` node under a group tree."""
    controls = list(node.get("controls") or [])
    for child_group in node.get("groups") or []:
        if isinstance(child_group, dict):
            controls.extend(_iter_controls(child_group))
    return controls


def parse(
    content: str,
    *,
    release_version: str,
    observed_at: datetime | None = None,
) -> ScanResult:
    """Parse Steampipe compliance-run JSON output text into a ``ScanResult``.

    Raises ``ValidationError`` for invalid JSON or a top-level shape that is
    not a benchmark group object.
    """
    moment = observed_at or datetime.now(UTC)
    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"steampipe output is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ValidationError("steampipe output must be a top-level JSON object")

    controls = _iter_controls(document)

    findings: list[Finding] = []
    unsupported: list[UnsupportedRecord] = []
    index = 0
    for control in controls:
        if not isinstance(control, dict):
            unsupported.append(
                UnsupportedRecord(
                    scanner=SCANNER,
                    record_index=index,
                    reason="control node is not a JSON object",
                    raw={"value": control},
                )
            )
            index += 1
            continue

        control_id_native = control.get("control_id")
        results = control.get("results")
        if not isinstance(results, list):
            unsupported.append(
                UnsupportedRecord(
                    scanner=SCANNER,
                    record_index=index,
                    reason="control node has no 'results' array",
                    raw=control,
                )
            )
            index += 1
            continue

        for result in results:
            if not isinstance(result, dict):
                unsupported.append(
                    UnsupportedRecord(
                        scanner=SCANNER,
                        record_index=index,
                        reason="result row is not a JSON object",
                        raw={"control_id": control_id_native, "value": result},
                    )
                )
                index += 1
                continue
            try:
                findings.append(
                    normalize_steampipe(
                        str(control_id_native),
                        result,
                        release_version=release_version,
                        observed_at=moment,
                    )
                )
            except UnsupportedRecordError as exc:
                unsupported.append(
                    UnsupportedRecord(
                        scanner=SCANNER,
                        record_index=index,
                        reason=str(exc),
                        raw={"control_id": control_id_native, **result},
                    )
                )
            index += 1

    return ScanResult(
        scanner=SCANNER,
        parser_version=PARSER_VERSION,
        findings=tuple(findings),
        unsupported=tuple(unsupported),
    )


__all__ = ["PARSER_VERSION", "SCANNER", "parse"]
