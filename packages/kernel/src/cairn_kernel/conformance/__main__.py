import argparse
import sys
from pathlib import Path

from cairn_kernel.conformance.registry import RuleMapError, load_rule_map
from cairn_kernel.conformance.runner import CheckStatus, run_rule_map

DEFAULT_RULES = Path("tools/conformance/rules.yaml")
DEFAULT_JSON = Path("build/conformance/results.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-conformance",
        description="Run the CAIRN conformance rule map and emit machine-readable results.",
    )
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)

    try:
        rules = load_rule_map(args.rules)
    except (OSError, RuleMapError) as exc:
        print(f"conformance: {exc}", file=sys.stderr)
        return 2

    report = run_rule_map(
        rules,
        cwd=Path.cwd(),
        timeout_seconds=args.timeout_seconds,
    )
    for result in report.results:
        if result.status is CheckStatus.PENDING:
            print(f"{result.status.value:<7} {result.rule.id} {result.rule.title}"
                  f" -> {result.rule.pending_story}")
        else:
            print(f"{result.status.value:<7} {result.rule.id} {result.rule.title}"
                  f" ({result.duration_ms}ms)")

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
