"""Per-scanner record-level normalization into the common Finding model.

Each scanner speaks its own vocabulary for a check/control id and its own
status enumeration. These functions map one already-parsed native record
(a plain mapping, as decoded from the scanner's JSON output) onto a
:class:`~cairn_modules.posture.findings.Finding`, or raise
:class:`UnsupportedRecordError` when the record cannot be mapped -- an
unrecognized check id, an unrecognized status, or a record missing a field
the mapping needs. Adapters in ``cairn_adapters.scanners`` catch that error
per record and turn it into a reported :class:`UnsupportedRecord`; nothing
is ever dropped silently.

The check-id -> control-id tables below are a deliberately small seed
mapping onto the R1-08 GCP CIS seed controls (``controls/gcp-cis-seed.yaml``).
Extending coverage to more checks/controls is later work; an unmapped id is
reported as unsupported, not guessed at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cairn_contracts.posture import ControlVersionReference

from cairn_modules.posture.findings import Finding, FindingStatus

PROWLER_CHECK_TO_CONTROL: dict[str, str] = {
    "iam_corporate_login_credentials": "gcp-cis-1.1",
    "iam_user_managed_service_account_key": "gcp-cis-1.4",
}

_PROWLER_STATUS: dict[str, FindingStatus] = {
    "PASS": FindingStatus.PASS,
    "FAIL": FindingStatus.FAIL,
    "MANUAL": FindingStatus.UNKNOWN,
}

STEAMPIPE_CONTROL_TO_CONTROL: dict[str, str] = {
    "gcp_cis_v200.control.cis_v200_3_1": "gcp-cis-3.1",
    "gcp_cis_v200.control.cis_v200_3_6": "gcp-cis-3.6",
}

_STEAMPIPE_STATUS: dict[str, FindingStatus] = {
    "ok": FindingStatus.PASS,
    "alarm": FindingStatus.FAIL,
    "info": FindingStatus.UNKNOWN,
    "skip": FindingStatus.UNKNOWN,
}

OPA_CONTROL_TO_CONTROL: dict[str, str] = {
    "cis_5_1": "gcp-cis-5.1",
    "cis_6_1": "gcp-cis-6.1",
}


class UnsupportedRecordError(Exception):
    """Raised when a native scanner record cannot be mapped to a Finding."""


def _require_field(record: dict[str, Any], key: str) -> Any:
    if key not in record or record[key] in (None, ""):
        raise UnsupportedRecordError(f"record is missing required field '{key}'")
    return record[key]


def normalize_prowler(
    record: dict[str, Any],
    *,
    release_version: str,
    observed_at: datetime,
) -> Finding:
    """Normalize one Prowler native-JSON finding record."""
    check_id = _require_field(record, "CheckID")
    control_id = PROWLER_CHECK_TO_CONTROL.get(check_id)
    if control_id is None:
        raise UnsupportedRecordError(f"prowler check '{check_id}' has no mapped control")

    status_raw = _require_field(record, "Status")
    status = _PROWLER_STATUS.get(status_raw)
    if status is None:
        raise UnsupportedRecordError(f"prowler status '{status_raw}' is not recognized")

    resource_id = _require_field(record, "ResourceId")

    return Finding(
        scanner="prowler",
        scanner_check_id=check_id,
        control_reference=ControlVersionReference(
            control_id=control_id, release_version=release_version
        ),
        status=status,
        resource_id=resource_id,
        resource_type=str(record.get("ResourceType") or "unknown"),
        message=str(record.get("StatusExtended") or record.get("CheckTitle") or ""),
        observed_at=observed_at,
        raw=record,
    )


def normalize_steampipe(
    control_id_native: str,
    result: dict[str, Any],
    *,
    release_version: str,
    observed_at: datetime,
) -> Finding:
    """Normalize one Steampipe compliance-run control result row."""
    control_id = STEAMPIPE_CONTROL_TO_CONTROL.get(control_id_native)
    if control_id is None:
        raise UnsupportedRecordError(
            f"steampipe control '{control_id_native}' has no mapped control"
        )

    status_raw = _require_field(result, "status")
    status = _STEAMPIPE_STATUS.get(status_raw)
    if status is None:
        raise UnsupportedRecordError(f"steampipe status '{status_raw}' is not recognized")

    resource_id = _require_field(result, "resource")

    return Finding(
        scanner="steampipe",
        scanner_check_id=control_id_native,
        control_reference=ControlVersionReference(
            control_id=control_id, release_version=release_version
        ),
        status=status,
        resource_id=resource_id,
        resource_type=str(result.get("resource_type") or "unknown"),
        message=str(result.get("reason") or ""),
        observed_at=observed_at,
        raw=result,
    )


def normalize_opa(
    record: dict[str, Any],
    *,
    release_version: str,
    observed_at: datetime,
) -> Finding:
    """Normalize one record from an OPA policy decision document.

    CAIRN's own rego policies emit one object per evaluated resource under
    ``result[0].expressions[0].value``, each carrying ``control_id``,
    ``resource_id``, ``resource_type``, ``allow`` and ``message``.
    """
    control_id_native = _require_field(record, "control_id")
    control_id = OPA_CONTROL_TO_CONTROL.get(control_id_native)
    if control_id is None:
        raise UnsupportedRecordError(f"opa control '{control_id_native}' has no mapped control")

    if "allow" not in record:
        raise UnsupportedRecordError("record is missing required field 'allow'")
    allow = record["allow"]
    if not isinstance(allow, bool):
        raise UnsupportedRecordError("record field 'allow' must be a boolean")
    status = FindingStatus.PASS if allow else FindingStatus.FAIL

    resource_id = _require_field(record, "resource_id")

    return Finding(
        scanner="opa",
        scanner_check_id=control_id_native,
        control_reference=ControlVersionReference(
            control_id=control_id, release_version=release_version
        ),
        status=status,
        resource_id=resource_id,
        resource_type=str(record.get("resource_type") or "unknown"),
        message=str(record.get("message") or ""),
        observed_at=observed_at,
        raw=record,
    )


__all__ = [
    "OPA_CONTROL_TO_CONTROL",
    "PROWLER_CHECK_TO_CONTROL",
    "STEAMPIPE_CONTROL_TO_CONTROL",
    "UnsupportedRecordError",
    "normalize_opa",
    "normalize_prowler",
    "normalize_steampipe",
]
