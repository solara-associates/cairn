"""Tests for R1-12 cost baseline and coverage/unallocated spend.

Covers the acceptance criterion: "Coverage shown; missing tags
reported."

- baseline-computation test: total/attributable/unallocated amounts
  aggregate correctly from canonical CostRecords;
- unallocated-spend test: a record with no attribution signal (tags)
  is shown explicitly, by cost id, and still counted in the total --
  never excluded;
- missing-tag report test: the same no-tags records are reported, by
  cost id, as a first-class output.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_modules.finops import (
    BillingLineItem,
    build_baseline,
    build_baselines,
    import_cost_records,
)

TENANT = "tenant-1"
PROJECT = "project-1"
ACCOUNT = "gcp-billing-acct-1"
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 10, 1, 1, tzinfo=UTC)


def _line_item(**overrides: object) -> BillingLineItem:
    fields: dict = {
        "source_id": "row-1",
        "provider": "gcp",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "account_id": ACCOUNT,
        "service": "Compute Engine",
        "region": "us-central1",
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "currency": "USD",
        "amount_minor": 1000,
        "tags": {"env": "prod"},
        "raw_ref": "gcp://acct/billing/row-1",
    }
    fields.update(overrides)
    return BillingLineItem(**fields)


def _records(*items: BillingLineItem):
    return import_cost_records(items, ingest_run_id="run-1", parser_version="test-1")


# --- baseline computation ----------------------------------------------------


def test_baseline_totals_tagged_and_untagged_records_correctly() -> None:
    tagged = _line_item(source_id="row-1", amount_minor=1000, tags={"env": "prod"})
    untagged = _line_item(source_id="row-2", amount_minor=500, tags={})
    records = _records(tagged, untagged)

    baseline = build_baseline(records, currency="USD")

    assert baseline.currency == "USD"
    assert baseline.total_amount_minor == 1500
    assert baseline.attributable_amount_minor == 1000
    assert baseline.unallocated_amount_minor == 500
    assert baseline.record_count == 2


def test_build_baseline_rejects_a_mismatched_currency() -> None:
    records = _records(_line_item(source_id="row-1", currency="GBP"))

    with pytest.raises(ValueError, match="group by currency"):
        build_baseline(records, currency="USD")


def test_build_baselines_groups_by_currency() -> None:
    usd = _line_item(source_id="row-1", currency="USD", amount_minor=1000)
    gbp = _line_item(source_id="row-2", currency="GBP", amount_minor=750)
    records = _records(usd, gbp)

    baselines = build_baselines(records)

    by_currency = {b.currency: b for b in baselines}
    assert set(by_currency) == {"USD", "GBP"}
    assert by_currency["USD"].total_amount_minor == 1000
    assert by_currency["GBP"].total_amount_minor == 750


# --- unallocated spend is shown, never excluded ------------------------------


def test_unallocated_cost_is_shown_explicitly_and_still_counted_in_the_total() -> None:
    attributable = _line_item(source_id="row-1", amount_minor=1000, tags={"env": "prod"})
    unallocated = _line_item(source_id="row-2", amount_minor=500, tags={})
    records = _records(attributable, unallocated)

    baseline = build_baseline(records, currency="USD")

    unallocated_record = next(r for r in records if r.tags == {})
    assert unallocated_record.cost_id in baseline.unallocated_cost_ids
    assert unallocated_record.cost_id not in baseline.attributable_cost_ids
    # Not excluded from the total -- the total is the sum of both buckets.
    assert baseline.total_amount_minor == baseline.attributable_amount_minor + baseline.unallocated_amount_minor
    assert baseline.total_amount_minor == 1500


def test_all_unallocated_batch_still_reports_a_nonzero_total() -> None:
    records = _records(_line_item(source_id="row-1", amount_minor=500, tags={}))

    baseline = build_baseline(records, currency="USD")

    assert baseline.attributable_cost_ids == ()
    assert baseline.total_amount_minor == 500
    assert baseline.unallocated_amount_minor == 500


# --- missing-tag reporting ----------------------------------------------------


def test_missing_tag_report_names_exactly_the_untagged_records() -> None:
    tagged = _line_item(source_id="row-1", tags={"env": "prod"})
    untagged_a = _line_item(source_id="row-2", tags={})
    untagged_b = _line_item(source_id="row-3", tags={})
    records = _records(tagged, untagged_a, untagged_b)

    baseline = build_baseline(records, currency="USD")

    untagged_cost_ids = {r.cost_id for r in records if r.provenance.source_id in ("row-2", "row-3")}
    assert set(baseline.missing_tag_cost_ids) == untagged_cost_ids
    tagged_cost_id = next(r.cost_id for r in records if r.provenance.source_id == "row-1")
    assert tagged_cost_id not in baseline.missing_tag_cost_ids


def test_a_record_with_any_tag_is_not_a_missing_tag_record() -> None:
    records = _records(_line_item(source_id="row-1", tags={"owner": "team-a"}))

    baseline = build_baseline(records, currency="USD")

    assert baseline.missing_tag_cost_ids == ()
