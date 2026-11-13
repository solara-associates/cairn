"""Prowler scanner adapter (R1-09).

Parses Prowler's native JSON check-output format (a top-level JSON array of
finding objects, one per check/resource) into a
:class:`~cairn_modules.posture.findings.ScanResult`. A record whose
``CheckID``, ``Status`` or ``ResourceId`` cannot be mapped is reported as an
:class:`~cairn_modules.posture.findings.UnsupportedRecord`, never dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cairn_kernel.errors import ValidationError
from cairn_modules.posture.findings import Finding, ScanResult, UnsupportedRecord
from cairn_modules.posture.normalization import UnsupportedRecordError, normalize_prowler

SCANNER = "prowler"
PARSER_VERSION = "prowler-adapter-1.0.0"


def parse(
    content: str,
    *,
    release_version: str,
    observed_at: datetime | None = None,
) -> ScanResult:
    """Parse Prowler native-JSON output text into a ``ScanResult``.

    Raises ``ValidationError`` for invalid JSON or a top-level shape that is
    not a JSON array of finding objects.
    """
    moment = observed_at or datetime.now(UTC)
    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"prowler output is not valid JSON: {exc}") from exc

    if not isinstance(document, list):
        raise ValidationError("prowler output must be a top-level JSON array of findings")

    findings: list[Finding] = []
    unsupported: list[UnsupportedRecord] = []
    for index, record in enumerate(document):
        if not isinstance(record, dict):
            unsupported.append(
                UnsupportedRecord(
                    scanner=SCANNER,
                    record_index=index,
                    reason="record is not a JSON object",
                    raw={"value": record},
                )
            )
            continue
        try:
            findings.append(
                normalize_prowler(record, release_version=release_version, observed_at=moment)
            )
        except UnsupportedRecordError as exc:
            unsupported.append(
                UnsupportedRecord(
                    scanner=SCANNER,
                    record_index=index,
                    reason=str(exc),
                    raw=record,
                )
            )

    return ScanResult(
        scanner=SCANNER,
        parser_version=PARSER_VERSION,
        findings=tuple(findings),
        unsupported=tuple(unsupported),
    )


__all__ = ["PARSER_VERSION", "SCANNER", "parse"]
