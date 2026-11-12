import json
import shlex
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

from cairn_kernel.conformance.exceptions import ExceptionRecord, validate_exceptions
from cairn_kernel.conformance.registry import Rule

OUTPUT_TAIL_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 900


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: Rule
    status: CheckStatus
    exit_code: int | None = None
    duration_ms: int | None = None
    output: str = ""


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    results: tuple[RuleResult, ...]
    generated_at: datetime
    errors: tuple[str, ...] = ()
    exceptions: tuple[ExceptionRecord, ...] = ()

    def _with_status(self, status: CheckStatus) -> tuple[RuleResult, ...]:
        return tuple(result for result in self.results if result.status is status)

    @property
    def passed(self) -> tuple[RuleResult, ...]:
        return self._with_status(CheckStatus.PASS)

    @property
    def failed(self) -> tuple[RuleResult, ...]:
        return self._with_status(CheckStatus.FAIL)

    @property
    def pending(self) -> tuple[RuleResult, ...]:
        return self._with_status(CheckStatus.PENDING)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "results": [
                {
                    "rule_id": result.rule.id,
                    "title": result.rule.title,
                    "owner": result.rule.owner,
                    "mandatory": result.rule.mandatory,
                    "status": result.status.value,
                    "check": result.rule.check,
                    "pending_story": result.rule.pending_story,
                    "evidence": list(result.rule.evidence),
                    "exception": _exception_payload(result.rule.id, self.exceptions),
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "output": result.output,
                }
                for result in self.results
            ],
            "errors": list(self.errors),
            "summary": {
                "total": len(self.results),
                "passed": len(self.passed),
                "failed": len(self.failed),
                "pending": len(self.pending),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _exception_payload(
    rule_id: str, exceptions: tuple[ExceptionRecord, ...]
) -> dict[str, object] | None:
    for record in exceptions:
        if record.rule_id == rule_id:
            return {
                "expires_on": record.expires_on.isoformat(),
                "owner": record.owner,
                "evidence": record.evidence,
                "reason": record.reason,
            }
    return None


def run_rule_map(
    rules: tuple[Rule, ...],
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    *,
    exceptions: tuple[ExceptionRecord, ...] = (),
    release: bool = False,
    today: date | None = None,
) -> ConformanceReport:
    results = tuple(_run_rule(rule, cwd, timeout_seconds) for rule in rules)
    errors = list(validate_exceptions(exceptions, rules, today=today))
    by_rule = {record.rule_id: record for record in exceptions}
    adjusted: list[RuleResult] = []
    for result in results:
        if result.status is not CheckStatus.PENDING:
            if result.rule.id in by_rule:
                errors.append(
                    f"exception for {result.rule.id} is stale: the rule is not pending"
                )
            adjusted.append(result)
            continue
        if release:
            adjusted.append(
                replace(
                    result,
                    status=CheckStatus.FAIL,
                    output="release build: mandatory rule is pending",
                )
            )
        elif result.rule.id not in by_rule:
            adjusted.append(
                replace(
                    result,
                    status=CheckStatus.FAIL,
                    output="mandatory rule is pending without an exception",
                )
            )
        else:
            adjusted.append(result)
    return ConformanceReport(
        results=tuple(adjusted),
        generated_at=datetime.now(UTC),
        errors=tuple(errors),
        exceptions=exceptions,
    )


def _run_rule(rule: Rule, cwd: Path, timeout_seconds: int) -> RuleResult:
    if rule.check is None:
        return RuleResult(rule=rule, status=CheckStatus.PENDING)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            shlex.split(rule.check),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RuleResult(
            rule=rule,
            status=CheckStatus.FAIL,
            duration_ms=_elapsed_ms(started),
            output=_tail(str(exc)),
        )
    return RuleResult(
        rule=rule,
        status=CheckStatus.PASS if completed.returncode == 0 else CheckStatus.FAIL,
        exit_code=completed.returncode,
        duration_ms=_elapsed_ms(started),
        output=_tail(completed.stdout + completed.stderr),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _tail(output: str) -> str:
    return output[-OUTPUT_TAIL_CHARS:]
