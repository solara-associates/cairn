"""OPA scanner adapter (R1-09).

Parses the output of ``opa eval -f json`` run against a CAIRN rego posture
policy into a :class:`~cairn_modules.posture.findings.ScanResult`. The
outer shape (``result[0].expressions[0].value``) is OPA's own documented
``eval`` output envelope; the inner ``value`` is a JSON array of one
decision object per evaluated resource, each carrying ``control_id``,
``resource_id``, ``resource_type``, ``allow`` and ``message`` -- the shape
CAIRN's posture rego policies are written to emit. A decision object whose
``control_id`` is unmapped, or that is missing a required field, is
reported as an :class:`~cairn_modules.posture.findings.UnsupportedRecord`,
never dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cairn_kernel.errors import ValidationError
from cairn_modules.posture.findings import Finding, ScanResult, UnsupportedRecord
from cairn_modules.posture.normalization import UnsupportedRecordError, normalize_opa

SCANNER = "opa"
PARSER_VERSION = "opa-adapter-1.0.0"


def _extract_decisions(document: Any) -> list[Any]:
    if not isinstance(document, dict):
        raise ValidationError("opa output must be a top-level JSON object")
    result = document.get("result")
    if not isinstance(result, list) or not result:
        raise ValidationError("opa output 'result' must be a non-empty array")
    first = result[0]
    if not isinstance(first, dict):
        raise ValidationError("opa output 'result[0]' must be an object")
    expressions = first.get("expressions")
    if not isinstance(expressions, list) or not expressions:
        raise ValidationError("opa output 'result[0].expressions' must be a non-empty array")
    expression = expressions[0]
    if not isinstance(expression, dict) or "value" not in expression:
        raise ValidationError("opa output 'result[0].expressions[0]' must carry a 'value'")
    value = expression["value"]
    if not isinstance(value, list):
        raise ValidationError(
            "opa output 'result[0].expressions[0].value' must be a JSON array of decisions"
        )
    return value


def parse(
    content: str,
    *,
    release_version: str,
    observed_at: datetime | None = None,
) -> ScanResult:
    """Parse ``opa eval -f json`` output text into a ``ScanResult``.

    Raises ``ValidationError`` for invalid JSON or an output shape that
    does not match OPA's documented ``eval`` envelope.
    """
    moment = observed_at or datetime.now(UTC)
    try:
        document: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"opa output is not valid JSON: {exc}") from exc

    decisions = _extract_decisions(document)

    findings: list[Finding] = []
    unsupported: list[UnsupportedRecord] = []
    for index, record in enumerate(decisions):
        if not isinstance(record, dict):
            unsupported.append(
                UnsupportedRecord(
                    scanner=SCANNER,
                    record_index=index,
                    reason="decision is not a JSON object",
                    raw={"value": record},
                )
            )
            continue
        try:
            findings.append(
                normalize_opa(record, release_version=release_version, observed_at=moment)
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
