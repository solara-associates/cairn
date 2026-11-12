import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

EVIDENCE_PATTERN = re.compile(r"^\S+$")


class ExceptionMapError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExceptionRecord:
    rule_id: str
    owner: str
    reason: str
    expires_on: date
    evidence: str

    @property
    def expired(self) -> bool:
        return self.expires_on < date.today()


def load_exceptions(path: Path) -> tuple[ExceptionRecord, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("exceptions"), list):
        raise ExceptionMapError(f"{path} must contain an 'exceptions' list")
    records = tuple(_parse_exception(entry, path) for entry in data["exceptions"])
    seen: set[str] = set()
    for record in records:
        if record.rule_id in seen:
            raise ExceptionMapError(f"duplicate exception for {record.rule_id}")
        seen.add(record.rule_id)
    return records


def _parse_exception(entry: object, path: Path) -> ExceptionRecord:
    if not isinstance(entry, dict):
        raise ExceptionMapError(f"{path}: each exception must be a mapping")
    missing = [
        field
        for field in ("rule_id", "owner", "reason", "expires_on", "evidence")
        if field not in entry
    ]
    if missing:
        raise ExceptionMapError(
            f"{path}: exception missing fields {', '.join(missing)}"
        )
    expires_on = entry["expires_on"]
    if isinstance(expires_on, date):
        expiry = expires_on
    else:
        try:
            expiry = date.fromisoformat(str(expires_on))
        except ValueError as exc:
            raise ExceptionMapError(
                f"{path}: invalid expires_on {expires_on!r}"
            ) from exc
    evidence = str(entry["evidence"]).strip()
    if not EVIDENCE_PATTERN.match(evidence):
        raise ExceptionMapError(
            f"{path}: {entry['rule_id']} needs a non-blank evidence reference"
        )
    return ExceptionRecord(
        rule_id=str(entry["rule_id"]),
        owner=str(entry["owner"]).strip() or _missing_owner(path, entry),
        reason=str(entry["reason"]).strip() or _missing_reason(path, entry),
        expires_on=expiry,
        evidence=evidence,
    )


def _missing_owner(path: Path, entry: dict[str, object]) -> str:
    raise ExceptionMapError(f"{path}: {entry['rule_id']} needs an owner")


def _missing_reason(path: Path, entry: dict[str, object]) -> str:
    raise ExceptionMapError(f"{path}: {entry['rule_id']} needs a reason")


def validate_exceptions(
    exceptions: tuple[ExceptionRecord, ...],
    rules: tuple[object, ...],
    *,
    today: date | None = None,
) -> tuple[str, ...]:
    today = today or date.today()
    known = {rule.id for rule in rules}
    errors: list[str] = []
    for record in exceptions:
        if record.rule_id not in known:
            errors.append(f"exception references unknown rule {record.rule_id}")
        if record.expires_on < today:
            errors.append(
                f"exception for {record.rule_id} expired on {record.expires_on.isoformat()}"
            )
    return tuple(errors)
