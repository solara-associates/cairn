import re
from dataclasses import dataclass
from pathlib import Path

import yaml

RULE_ID_PATTERN = re.compile(r"^R-[A-Z]+-\d{2}$")
PENDING_STORY_PATTERN = re.compile(r"^R\d-\d{2}$")
EVIDENCE_PATTERN = re.compile(r"^\S+$")

V0_RULE_TITLES: dict[str, str] = {
    "R-ARCH-01": "importlinter all contracts kept",
    "R-ARCH-02": "Domain imports no SDK/framework",
    "R-TENANT-01": "Every repository query enforces tenant context",
    "R-TENANT-02": (
        "Every tenant-owned and project-owned table has forced RLS and required"
        " policies; app roles lack BYPASSRLS; tests run under the app role"
    ),
    "R-AUDIT-01": (
        "Class B/C mutations append audit trail; Class C appends before external"
        " effect"
    ),
    "R-EVID-01": "Evidence tamper/fork is detected",
    "R-AI-01": "Model output schema-validated",
    "R-AI-02": "Model cannot approve/execute",
    "R-MAP-01": "Approximate/unavailable never rendered as exact",
    "R-REV-01": "Approvals/executions bind to immutable revision rows and exact hashes",
    "R-GATE-01": (
        "No Class C path outside ExecutionGatePort; no production provider"
        " adapter before R4"
    ),
    "R-MUT-01": (
        "Every command declares a mutation class; operation and mutation classes"
        " agree; external classes have a validated recovery strategy before"
        " authorization"
    ),
    "R-MUT-02": (
        "Every external mutation has a complete compensation contract (strategy,"
        " preconditions, authority, evidence, failure handling) matching its"
        " mutation class; an incomplete contract blocks authorization"
    ),
    "R-IDEM-01": (
        "Class B and Class C mutations require tenant/project/operation/key"
        " scoped idempotency, canonical request hashing, replay/conflict"
        " handling and expiry"
    ),
    "R-OUTBOX-01": (
        "Outbox failure semantics proven by failure injection: crash after"
        " commit before dispatch loses nothing; duplicate delivery is"
        " idempotent; consumer crash after effect before acknowledgement does"
        " not repeat the effect; dead-letter replay preserves ordering and"
        " runbook; replay cannot cross tenant scope"
    ),
    "R-TENANT-03": (
        "Adversarial RLS under the application role: missing tenant context"
        " fails closed; pooled connections cannot leak tenant context;"
        " tenant-context change attempts are rejected and audited"
    ),
    "R-COV-01": "Coverage floor per critical package",
    "R-SEC-01": "No critical/high findings; high needs risk acceptance",
    "R-SEC-02": "SBOM and image signature present",
    "R-CONF-01": "Every mandatory rule maps to a check",
    "R-OPCLASS-01": (
        "Every existing API, MCP tool/resource, event and worker job carries an"
        " operation class and mutation class, with a tenancy scope and, for"
        " external mutations, a complete compensation contract; new or removed"
        " surfaces fail this check until the matrix is updated"
    ),
}


class RuleMapError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    title: str
    owner: str
    mandatory: bool
    check: str | None = None
    pending_story: str | None = None
    evidence: tuple[str, ...] = ()


def load_rule_map(path: Path) -> tuple[Rule, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RuleMapError(f"{path} must contain a 'rules' list")
    rules = tuple(_parse_rule(entry, path) for entry in data["rules"])
    validate_rule_map(rules)
    return rules


def _parse_rule(entry: object, path: Path) -> Rule:
    if not isinstance(entry, dict):
        raise RuleMapError(f"{path}: each rule must be a mapping")
    missing = [field for field in ("id", "title", "owner", "mandatory") if field not in entry]
    if missing:
        raise RuleMapError(f"{path}: rule missing fields {', '.join(missing)}")
    check = entry.get("check")
    pending_story = entry.get("pending_story")
    return Rule(
        id=str(entry["id"]),
        title=str(entry["title"]),
        owner=str(entry["owner"]),
        mandatory=bool(entry["mandatory"]),
        check=None if check is None else str(check),
        pending_story=None if pending_story is None else str(pending_story),
        evidence=_parse_evidence(entry.get("evidence"), entry, path),
    )


def _parse_evidence(value: object, entry: dict[str, object], path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = tuple(value)
    else:
        raise RuleMapError(f"{path}: {entry['id']} evidence must be text or a list")
    for item in items:
        if not EVIDENCE_PATTERN.match(item):
            raise RuleMapError(f"{path}: {entry['id']} has a blank evidence entry")
    return items


def validate_rule_map(rules: tuple[Rule, ...]) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise RuleMapError(f"duplicate rule id: {rule.id}")
        seen.add(rule.id)
        _validate_rule(rule)


def _validate_rule(rule: Rule) -> None:
    if not RULE_ID_PATTERN.match(rule.id):
        raise RuleMapError(f"invalid rule id: {rule.id!r}")
    expected_title = V0_RULE_TITLES.get(rule.id)
    if expected_title is None:
        raise RuleMapError(f"{rule.id} is not a v0 mandatory rule")
    if rule.title != expected_title:
        raise RuleMapError(f"{rule.id}: title does not match the v0 rule map")
    if not rule.owner.strip():
        raise RuleMapError(f"{rule.id}: owner is required")
    if rule.check is not None and not rule.check.strip():
        raise RuleMapError(f"{rule.id}: check must not be blank")
    if rule.check is not None and rule.mandatory and not rule.evidence:
        raise RuleMapError(f"{rule.id}: active mandatory rule needs evidence")
    if rule.check is not None and rule.pending_story is not None:
        raise RuleMapError(f"{rule.id}: declare either a check or a pending_story")
    if rule.mandatory and rule.check is None and rule.pending_story is None:
        raise RuleMapError(f"{rule.id}: mandatory rule needs a check or a pending_story")
    if rule.pending_story is not None and not PENDING_STORY_PATTERN.match(rule.pending_story):
        raise RuleMapError(f"{rule.id}: invalid pending story {rule.pending_story!r}")
