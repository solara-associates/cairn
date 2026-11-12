import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

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
        return not self.failed

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
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "output": result.output,
                }
                for result in self.results
            ],
            "summary": {
                "total": len(self.results),
                "passed": len(self.passed),
                "failed": len(self.failed),
                "pending": len(self.pending),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def run_rule_map(
    rules: tuple[Rule, ...],
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ConformanceReport:
    results = tuple(_run_rule(rule, cwd, timeout_seconds) for rule in rules)
    return ConformanceReport(results=results, generated_at=datetime.now(UTC))


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
