"""R0-20 gate 1: ADR-008/009/010/012 acceptance status is CI-enforced.

The R0-20 review found this gate documentation-only: the decision log in
``docs/adr/README.md`` marks all four ADRs "Accepted (amended)", but nothing
in CI checked that status, so a reversion (deliberate or accidental) back to
"Proposed" would go unnoticed. This test parses the decision-log table and
each ADR file's own ``Status:`` header, and fails if either ever reads
anything other than "Accepted" or "Accepted (amended)" for one of these four
ADRs, or if the two disagree.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
ADR_README = REPO_ROOT / "docs/adr/README.md"

# The four ADRs this gate covers, and the file each one lives in.
GATED_ADRS: dict[str, str] = {
    "ADR-008": "ADR-008-evidence.md",
    "ADR-009": "ADR-009-approval-binding.md",
    "ADR-010": "ADR-010-gated-writes.md",
    "ADR-012": "ADR-012-tenant-isolation.md",
}

ALLOWED_STATUSES = frozenset({"Accepted", "Accepted (amended)"})

# Matches a decision-log row like:
# | [ADR-008](ADR-008-evidence.md) | title text | Accepted (amended) | 2026-11-09 |
_DECISION_LOG_ROW = re.compile(
    r"^\|\s*\[(ADR-\d+)\]\([^)]*\)\s*\|.*?\|\s*(Accepted(?: \(amended\))?|Proposed|Rejected|Superseded[^|]*)\s*\|",
)

# Matches an ADR file's own header line, e.g.:
# - **Status:** Accepted (amended 9 November 2026 after architecture review)
_ADR_STATUS_HEADER = re.compile(
    r"^\s*-?\s*\*{0,2}Status:?\*{0,2}\s*:?\s*(Accepted(?: \(amended[^)]*\))?|Proposed|Rejected|Superseded[^\n]*)",
    re.IGNORECASE,
)


def _parse_decision_log() -> dict[str, str]:
    text = ADR_README.read_text(encoding="utf-8")
    statuses: dict[str, str] = {}
    for line in text.splitlines():
        match = _DECISION_LOG_ROW.match(line)
        if match:
            adr_id, status = match.groups()
            statuses[adr_id] = status.strip()
    return statuses


def _parse_adr_header_status(adr_id: str) -> str:
    adr_path = REPO_ROOT / "docs/adr" / GATED_ADRS[adr_id]
    text = adr_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = _ADR_STATUS_HEADER.match(line)
        if match:
            return match.group(1).strip()
    raise AssertionError(f"{adr_path} has no Status: header line")


def test_decision_log_parses_all_four_gated_adrs() -> None:
    statuses = _parse_decision_log()
    for adr_id in GATED_ADRS:
        assert adr_id in statuses, (
            f"{adr_id} is missing from the decision-log table in {ADR_README}"
        )


def test_decision_log_status_is_accepted_for_gated_adrs() -> None:
    statuses = _parse_decision_log()
    for adr_id in GATED_ADRS:
        status = statuses.get(adr_id)
        assert status in ALLOWED_STATUSES, (
            f"{adr_id} decision-log status is {status!r}, expected one of "
            f"{sorted(ALLOWED_STATUSES)}"
        )


def test_adr_file_status_header_is_accepted_for_gated_adrs() -> None:
    for adr_id in GATED_ADRS:
        header_status = _parse_adr_header_status(adr_id)
        # The header carries free-text amendment detail after "Accepted"; only
        # the leading word needs to match the allowed vocabulary.
        assert header_status.split(" (")[0].strip() == "Accepted", (
            f"{adr_id}'s own Status: header reads {header_status!r}, expected "
            "it to start with 'Accepted'"
        )


def test_decision_log_and_adr_file_agree_on_acceptance() -> None:
    statuses = _parse_decision_log()
    for adr_id in GATED_ADRS:
        log_status = statuses[adr_id]
        header_status = _parse_adr_header_status(adr_id)
        log_accepted = log_status.startswith("Accepted")
        header_accepted = header_status.split(" (")[0].strip() == "Accepted"
        assert log_accepted == header_accepted, (
            f"{adr_id}: decision-log status {log_status!r} disagrees with "
            f"the ADR's own header status {header_status!r}"
        )
