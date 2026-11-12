import shlex
from pathlib import Path

from cairn_kernel.conformance.exceptions import (
    load_exceptions,
    validate_exceptions,
)
from cairn_kernel.conformance.registry import V0_RULE_TITLES, load_rule_map

REPO_ROOT = Path(__file__).parents[2]
RULES_FILE = REPO_ROOT / "tools/conformance/rules.yaml"
EXCEPTIONS_FILE = REPO_ROOT / "tools/conformance/exceptions.yaml"

SPEC_RULE_IDS = frozenset(
    {
        "R-ARCH-01",
        "R-ARCH-02",
        "R-TENANT-01",
        "R-TENANT-02",
        "R-AUDIT-01",
        "R-EVID-01",
        "R-AI-01",
        "R-AI-02",
        "R-MAP-01",
        "R-REV-01",
        "R-GATE-01",
        "R-MUT-01",
        "R-MUT-02",
        "R-IDEM-01",
        "R-OUTBOX-01",
        "R-TENANT-03",
        "R-COV-01",
        "R-SEC-01",
        "R-SEC-02",
        "R-CONF-01",
    }
)


def test_rule_map_covers_every_v0_mandatory_rule() -> None:
    rules = load_rule_map(RULES_FILE)
    ids = {rule.id for rule in rules}
    assert ids == SPEC_RULE_IDS
    assert ids == set(V0_RULE_TITLES)


def test_every_mandatory_rule_maps_to_a_check_or_a_pending_story() -> None:
    for rule in load_rule_map(RULES_FILE):
        assert rule.mandatory, f"{rule.id} must be mandatory in v0"
        assert (rule.check is None) != (rule.pending_story is None), rule.id


def test_active_checks_reference_existing_files() -> None:
    for rule in load_rule_map(RULES_FILE):
        if rule.check is None:
            continue
        for token in shlex.split(rule.check):
            if token.endswith(".py") and not token.startswith("-"):
                assert (REPO_ROOT / token).exists(), f"{rule.id} references missing {token}"


def test_every_pending_rule_has_a_current_exception() -> None:
    rules = load_rule_map(RULES_FILE)
    exceptions = load_exceptions(EXCEPTIONS_FILE)
    pending = {rule.id for rule in rules if rule.pending_story is not None}
    excepted = {record.rule_id for record in exceptions}
    assert excepted == pending
    assert validate_exceptions(exceptions, rules) == ()
    for record in exceptions:
        assert (REPO_ROOT / record.evidence).exists(), (
            f"{record.rule_id} exception references missing {record.evidence}"
        )


def test_active_rules_publish_existing_evidence() -> None:
    for rule in load_rule_map(RULES_FILE):
        if rule.check is None:
            continue
        assert rule.evidence, f"{rule.id} needs evidence"
        for reference in rule.evidence:
            if reference.endswith((".py", ".md", ".yaml", ".toml")):
                assert (REPO_ROOT / reference).exists(), (
                    f"{rule.id} evidence references missing {reference}"
                )


def test_self_test_rule_runs_this_file() -> None:
    rules = {rule.id: rule for rule in load_rule_map(RULES_FILE)}
    check = rules["R-CONF-01"].check
    assert check is not None
    assert "tests/conformance/test_rule_map.py" in check
