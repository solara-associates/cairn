"""Common Finding model for posture scanner adapters (R1-09).

Every scanner adapter (Prowler, Steampipe, OPA) normalizes its own native
output into this shared shape. A ``Finding`` always references the exact
R1-08 control version it was evaluated against
(:class:`cairn_contracts.posture.ControlVersionReference`); a native record
that cannot be mapped onto a known control, or that is otherwise malformed,
is never silently dropped -- it is reported as an :class:`UnsupportedRecord`
so coverage gaps stay visible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from cairn_contracts.posture import ControlVersionReference


class FindingStatus(str, Enum):
    """The scanner's own verdict for one evaluated resource."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Finding:
    """One normalized posture evaluation result, common to every scanner."""

    scanner: str
    scanner_check_id: str
    control_reference: ControlVersionReference
    status: FindingStatus
    resource_id: str
    resource_type: str
    message: str
    observed_at: datetime
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))


@dataclass(frozen=True, slots=True)
class UnsupportedRecord:
    """A native scanner record that could not be normalized into a Finding.

    Raised reasons include an unmapped check/control id, a status the
    adapter does not recognize, or a record missing fields the adapter
    requires. The record is reported, never dropped.
    """

    scanner: str
    record_index: int
    reason: str
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The full normalized output of parsing one scanner's native output."""

    scanner: str
    parser_version: str
    findings: tuple[Finding, ...]
    unsupported: tuple[UnsupportedRecord, ...]

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)

    @property
    def record_count(self) -> int:
        return self.finding_count + self.unsupported_count


__all__ = [
    "Finding",
    "FindingStatus",
    "ScanResult",
    "UnsupportedRecord",
]
