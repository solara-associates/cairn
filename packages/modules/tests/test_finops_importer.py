"""R1-11: canonicalizing billing line items into CostRecords."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import ValidationError
from cairn_modules.finops import BillingLineItem, import_cost_records, to_cost_record

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
        "amount_minor": 1234,
        "tags": {"env": "prod"},
        "raw_ref": "gcp://acct/billing/row-1",
    }
    fields.update(overrides)
    return BillingLineItem(**fields)


def test_to_cost_record_carries_currency_period_tags_and_provenance() -> None:
    item = _line_item()
    ingested_at = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
    record = to_cost_record(
        item, ingest_run_id="run-1", parser_version="test-1", ingested_at=ingested_at
    )

    assert record.cost_id == "gcp:gcp-billing-acct-1:row-1"
    assert record.currency == "USD"
    assert record.period_start == PERIOD_START
    assert record.period_end == PERIOD_END
    assert record.tags == {"env": "prod"}
    assert record.provenance.source_system == "gcp"
    assert record.provenance.source_id == "row-1"
    assert record.provenance.parser_version == "test-1"
    assert record.provenance.ingest_run_id == "run-1"
    assert record.provenance.ingested_at == ingested_at
    assert record.provenance.observed_at == PERIOD_END
    assert record.provenance.raw_ref == "gcp://acct/billing/row-1"


def test_missing_tags_are_captured_as_an_explicit_empty_dict() -> None:
    item = _line_item(tags={})
    record = to_cost_record(
        item,
        ingest_run_id="run-1",
        parser_version="test-1",
        ingested_at=datetime.now(UTC),
    )
    assert record.tags == {}


def test_import_cost_records_stamps_every_record_with_the_same_ingested_at() -> None:
    items = (_line_item(source_id="row-1"), _line_item(source_id="row-2"))
    clock_calls = iter([datetime(2026, 11, 13, 11, 0, tzinfo=UTC)])
    records = import_cost_records(
        items,
        ingest_run_id="run-1",
        parser_version="test-1",
        clock=lambda: next(clock_calls),
    )
    assert len(records) == 2
    assert records[0].provenance.ingested_at == records[1].provenance.ingested_at


def test_billing_line_item_rejects_an_invalid_currency() -> None:
    with pytest.raises(ValidationError):
        _line_item(currency="us")


def test_billing_line_item_rejects_a_period_that_does_not_advance() -> None:
    with pytest.raises(ValidationError):
        _line_item(period_start=PERIOD_END, period_end=PERIOD_START)


def test_billing_line_item_rejects_a_blank_required_field() -> None:
    with pytest.raises(ValidationError):
        _line_item(service="")
