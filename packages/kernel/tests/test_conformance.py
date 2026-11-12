import json
import shlex
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml
from cairn_kernel.conformance import (
    CheckStatus,
    ExceptionMapError,
    ExceptionRecord,
    Rule,
    RuleMapError,
    load_exceptions,
    load_rule_map,
    run_rule_map,
)
from cairn_kernel.conformance.registry import V0_RULE_TITLES

SELF_TEST_ID = "R-CONF-01"


def _rule(rule_id: str = SELF_TEST_ID, **kwargs: object) -> Rule:
    return Rule(
        id=rule_id,
        title=V0_RULE_TITLES[rule_id],
        owner="conformance",
        mandatory=True,
        **kwargs,
    )


def _write_map(tmp_path: Path, *rules: Rule) -> Path:
    entries = []
    for rule in rules:
        entry: dict[str, object] = {
            "id": rule.id,
            "title": rule.title,
            "owner": rule.owner,
            "mandatory": rule.mandatory,
        }
        if rule.check is not None:
            entry["check"] = rule.check
            entry["evidence"] = ["tests/conformance/test_rule_map.py"]
        if rule.pending_story is not None:
            entry["pending_story"] = rule.pending_story
        entries.append(entry)
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump({"version": 0, "rules": entries}), encoding="utf-8")
    return path


def _exception(
    rule_id: str = SELF_TEST_ID, expires_on: date = date(2099, 1, 1), **kwargs: object
) -> ExceptionRecord:
    return ExceptionRecord(
        rule_id=rule_id,
        owner="conformance",
        reason="pending until the implementing story lands",
        expires_on=expires_on,
        evidence="tests/conformance/test_rule_map.py",
        **kwargs,
    )


def _python(code: str) -> str:
    return shlex.join([sys.executable, "-c", code])


def test_load_rule_map_parses_check_and_pending_entries(tmp_path: Path) -> None:
    path = _write_map(
        tmp_path,
        _rule(check=_python("pass")),
        _rule("R-AUDIT-01", pending_story="R0-10"),
    )
    rules = load_rule_map(path)
    assert [rule.id for rule in rules] == [SELF_TEST_ID, "R-AUDIT-01"]
    assert rules[0].check == _python("pass")
    assert rules[0].evidence == ("tests/conformance/test_rule_map.py",)
    assert rules[1].pending_story == "R0-10"


def test_load_rule_map_rejects_unknown_rule_id(tmp_path: Path) -> None:
    stray = Rule(
        id="R-ARCH-99",
        title="Unknown rule",
        owner="conformance",
        mandatory=True,
        check=_python("pass"),
    )
    path = _write_map(tmp_path, stray)
    with pytest.raises(RuleMapError, match="not a v0 mandatory rule"):
        load_rule_map(path)


def test_load_rule_map_rejects_duplicate_rule_ids(tmp_path: Path) -> None:
    path = _write_map(tmp_path, _rule(check=_python("pass")), _rule(check=_python("pass")))
    with pytest.raises(RuleMapError, match="duplicate rule id"):
        load_rule_map(path)


def test_load_rule_map_rejects_title_drift(tmp_path: Path) -> None:
    stray = _rule(check=_python("pass"))
    path = tmp_path / "rules.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "id": stray.id,
                        "title": "Something else",
                        "owner": stray.owner,
                        "mandatory": True,
                        "check": stray.check,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuleMapError, match="title does not match"):
        load_rule_map(path)


def test_load_rule_map_rejects_check_and_pending_together(tmp_path: Path) -> None:
    path = _write_map(tmp_path, _rule(check=_python("pass"), pending_story="R0-08"))
    with pytest.raises(RuleMapError, match="either a check or a pending_story"):
        load_rule_map(path)


def test_load_rule_map_rejects_unmapped_mandatory_rule(tmp_path: Path) -> None:
    path = _write_map(tmp_path, _rule())
    with pytest.raises(RuleMapError, match="needs a check or a pending_story"):
        load_rule_map(path)


def test_load_rule_map_rejects_invalid_pending_story(tmp_path: Path) -> None:
    path = _write_map(tmp_path, _rule(pending_story="backlog"))
    with pytest.raises(RuleMapError, match="invalid pending story"):
        load_rule_map(path)


def test_runner_fails_pending_rules_without_an_exception(tmp_path: Path) -> None:
    report = run_rule_map((_rule(pending_story="R0-08"),), cwd=tmp_path)
    assert report.results[0].status is CheckStatus.FAIL
    assert report.results[0].exit_code is None
    assert "without an exception" in report.results[0].output
    assert not report.ok


def test_runner_keeps_pending_rules_with_an_exception(tmp_path: Path) -> None:
    exception = _exception(rule_id=SELF_TEST_ID)
    report = run_rule_map(
        (_rule(pending_story="R0-08"),), cwd=tmp_path, exceptions=(exception,)
    )
    assert report.results[0].status is CheckStatus.PENDING
    assert report.ok


def test_release_fails_on_pending_rules_even_with_an_exception(tmp_path: Path) -> None:
    exception = _exception(rule_id=SELF_TEST_ID)
    report = run_rule_map(
        (_rule(pending_story="R0-08"),),
        cwd=tmp_path,
        exceptions=(exception,),
        release=True,
    )
    assert report.results[0].status is CheckStatus.FAIL
    assert "release build" in report.results[0].output
    assert not report.ok


def test_stale_exception_fails_conformance(tmp_path: Path) -> None:
    exception = _exception(rule_id=SELF_TEST_ID)
    report = run_rule_map(
        (_rule(check=_python("pass")),), cwd=tmp_path, exceptions=(exception,)
    )
    assert report.ok is False
    assert report.errors == (
        f"exception for {SELF_TEST_ID} is stale: the rule is not pending",
    )


def test_expired_exception_fails_conformance(tmp_path: Path) -> None:
    exception = _exception(rule_id=SELF_TEST_ID, expires_on=date(2020, 1, 1))
    report = run_rule_map(
        (_rule(pending_story="R0-08"),), cwd=tmp_path, exceptions=(exception,)
    )
    assert not report.ok
    assert "expired on 2020-01-01" in report.errors[0]


def test_exception_map_rejects_unknown_rule(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "exceptions": [
                    {
                        "rule_id": "R-NOPE-99",
                        "owner": "nobody",
                        "reason": "none",
                        "expires_on": "2027-01-01",
                        "evidence": "docs/remediation/CA-007-conformance-enforcement.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rules = (_rule(pending_story="R0-08"),)
    exceptions = load_exceptions(path)
    report = run_rule_map(rules, cwd=tmp_path, exceptions=exceptions)
    assert not report.ok
    assert "unknown rule R-NOPE-99" in report.errors[0]


def test_exception_map_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.yaml"
    entry = {
        "rule_id": SELF_TEST_ID,
        "owner": "conformance",
        "reason": "none",
        "expires_on": "2027-01-01",
        "evidence": "tests/conformance/test_rule_map.py",
    }
    path.write_text(
        yaml.safe_dump({"exceptions": [entry, entry]}), encoding="utf-8"
    )
    with pytest.raises(ExceptionMapError, match="duplicate exception"):
        load_exceptions(path)


def test_runner_passes_zero_exit_checks(tmp_path: Path) -> None:
    report = run_rule_map((_rule(check=_python("pass")),), cwd=tmp_path)
    result = report.results[0]
    assert result.status is CheckStatus.PASS
    assert result.exit_code == 0
    assert result.duration_ms is not None


def test_runner_fails_nonzero_exit_checks(tmp_path: Path) -> None:
    report = run_rule_map((_rule(check=_python("raise SystemExit(3)")),), cwd=tmp_path)
    assert report.results[0].status is CheckStatus.FAIL
    assert report.results[0].exit_code == 3
    assert not report.ok
    assert report.failed == report.results


def test_runner_captures_check_output(tmp_path: Path) -> None:
    report = run_rule_map((_rule(check=_python("print('checked')")),), cwd=tmp_path)
    assert "checked" in report.results[0].output


def test_report_serializes_machine_readable_results(tmp_path: Path) -> None:
    report = run_rule_map(
        (_rule(check=_python("pass")), _rule("R-AUDIT-01", pending_story="R0-10")),
        cwd=tmp_path,
    )
    payload = json.loads(report.to_json())
    assert payload["summary"] == {"total": 2, "passed": 1, "failed": 1, "pending": 0}
    assert "without an exception" in payload["results"][1]["output"]
    assert payload["results"][1]["rule_id"] == "R-AUDIT-01"
    assert payload["results"][1]["pending_story"] == "R0-10"
