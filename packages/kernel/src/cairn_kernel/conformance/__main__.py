import argparse
import sys
from datetime import date
from pathlib import Path

from cairn_kernel.conformance.exceptions import (
    ExceptionMapError,
    load_exceptions,
)
from cairn_kernel.conformance.registry import RuleMapError, load_rule_map
from cairn_kernel.conformance.runner import CheckStatus, run_rule_map

DEFAULT_RULES = Path("tools/conformance/rules.yaml")
DEFAULT_JSON = Path("build/conformance/results.json")
DEFAULT_EXCEPTIONS = Path("tools/conformance/exceptions.yaml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-conformance",
        description="Run the CAIRN conformance rule map and emit machine-readable results.",
    )
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--exceptions", type=Path, default=DEFAULT_EXCEPTIONS)
    parser.add_argument(
        "--release",
        action="store_true",
        help="treat any pending mandatory rule as a failure",
    )
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    try:
        rules = load_rule_map(args.rules)
        exceptions = load_exceptions(args.exceptions)
    except (OSError, RuleMapError, ExceptionMapError) as exc:
        print(f"conformance: {exc}", file=sys.stderr)
        return 2

    report = run_rule_map(
        rules,
        cwd=Path.cwd(),
        timeout_seconds=args.timeout_seconds,
        exceptions=exceptions,
        release=args.release,
        today=args.today,
    )
    expiries = {record.rule_id: record.expires_on for record in exceptions}
    for result in report.results:
        if result.status is CheckStatus.PENDING:
            expiry = expiries.get(result.rule.id)
            suffix = "" if expiry is None else f" (exception expires {expiry.isoformat()})"
            print(f"{result.status.value:<7} {result.rule.id} {result.rule.title}"
                  f" -> {result.rule.pending_story}{suffix}")
        else:
            print(f"{result.status.value:<7} {result.rule.id} {result.rule.title}"
                  f" ({result.duration_ms}ms)")

    for error in report.errors:
        print(f"ERROR   {error}")

    mandatory = sum(1 for rule in rules if rule.mandatory)
    print(
        f"Summary: {len(report.passed)} passed, {len(report.failed)} failed,"
        f" {len(report.pending)} pending of {mandatory} mandatory rules"
    )

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(report.to_json() + "\n", encoding="utf-8")
    print(f"Wrote {args.json}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
