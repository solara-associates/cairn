"""R0-20 gate 12 (incident-response half): the incident-response runbook
must reference real, currently-instrumented observability signals, not
invented or stale ones.

``docs/runbooks/incident-response.md`` carries an "Instrumented signals"
table of ``| signal | source file |`` rows. This test parses that table and
asserts, for every row, that the source file exists and its current
content contains the signal literally. A rename or removal of a metric
name, log field or event name in
``packages/kernel/src/cairn_kernel/observability/`` (or the audit-ledger
migrations the evidence-preservation section leans on) fails this test
until the runbook's table is updated to match.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "incident-response.md"

TABLE_ROW_PATTERN = re.compile(
    r"^\|\s*`(?P<signal>[^`]+)`\s*\|\s*`(?P<source>[^`]+)`\s*\|$"
)


def _signal_table_rows() -> list[tuple[str, str]]:
    text = RUNBOOK.read_text(encoding="utf-8")
    rows = [
        (match["signal"], match["source"])
        for line in text.splitlines()
        if (match := TABLE_ROW_PATTERN.match(line.strip()))
    ]
    return rows


def test_runbook_exists() -> None:
    assert RUNBOOK.exists(), f"missing {RUNBOOK}"


def test_signal_table_is_non_empty() -> None:
    rows = _signal_table_rows()
    assert len(rows) >= 5, (
        "docs/runbooks/incident-response.md's Instrumented signals table"
        " parsed to fewer than 5 rows -- check the table's `| `signal`"
        " | `path` |` format did not change"
    )


def test_every_referenced_signal_exists_in_its_named_source() -> None:
    rows = _signal_table_rows()
    assert rows, "no signal rows parsed from the runbook"
    for signal, source in rows:
        source_path = REPO_ROOT / source
        assert source_path.exists(), (
            f"incident-response.md names {source!r} for signal {signal!r},"
            " but that file does not exist"
        )
        content = source_path.read_text(encoding="utf-8")
        assert signal in content, (
            f"incident-response.md claims signal {signal!r} is instrumented in"
            f" {source!r}, but that literal string is not present there --"
            " the runbook has drifted from the real observability kit"
        )


def test_every_source_file_is_under_the_expected_directories() -> None:
    # Keeps the table honest about *what kind* of thing it is pointing at:
    # the observability kit itself, or the audit-ledger migrations the
    # evidence-preservation section depends on.
    allowed_prefixes = (
        "packages/kernel/src/cairn_kernel/observability/",
        "packages/adapters/src/cairn_adapters/persistence_postgres/migrations/",
    )
    for _signal, source in _signal_table_rows():
        assert source.startswith(allowed_prefixes), (
            f"{source!r} is outside the observability kit and the audit-ledger"
            " migrations -- update this test if the runbook now legitimately"
            " references a different real signal source"
        )
