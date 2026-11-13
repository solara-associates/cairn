"""R1-11: the GCP billing import adapter.

A golden fixture test asserts the exact canonical ``CostRecord`` output
(currency, period, tags, provenance) for a sample GCP billing export; a
missing-tag test asserts that rows with no tags import cleanly with their
tags visibly empty rather than being dropped. No live GCP billing export
is called -- ``GcpBillingFileSource`` reads a fixture file under
``tests/fixtures/gcp_billing/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.provider_core.contract import assert_billing_contract
from cairn_adapters.provider_core.ports import (
    BillingRequest,
    ProviderCapability,
    ProviderConnection,
)
from cairn_adapters.provider_gcp.billing import GcpBillingAdapter, GcpBillingFileSource
from cairn_kernel.errors import ValidationError

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "gcp_billing"

TENANT = "tenant-1"
PROJECT = "project-1"
ACCOUNT = "gcp-billing-acct-1"
NOW = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)


def _connection(*, account_id: str = ACCOUNT) -> ProviderConnection:
    return ProviderConnection(
        connection_id="conn-billing-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="gcp",
        account_id=account_id,
        credential_ref="secret://gcp/conn-billing-1",
    )


def _adapter(fixture_name: str) -> GcpBillingAdapter:
    return GcpBillingAdapter(
        source=GcpBillingFileSource(path=FIXTURES / fixture_name),
        clock=lambda: NOW,
    )


def _request(*, account_id: str = ACCOUNT, page_size: int = 100) -> BillingRequest:
    return BillingRequest(
        connection=_connection(account_id=account_id),
        period_start=datetime(2026, 9, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 1, tzinfo=UTC),
        page_size=page_size,
    )


def test_descriptor_declares_billing_only_and_read_only() -> None:
    adapter = _adapter("golden.json")
    descriptor = adapter.descriptor
    assert descriptor.provider == "gcp"
    assert descriptor.read_only
    assert descriptor.capabilities == frozenset({ProviderCapability.BILLING})


def test_golden_fixture_produces_exact_canonical_cost_records() -> None:
    adapter = _adapter("golden.json")
    page = adapter.read_billing(_request())
    records = {record.cost_id: record for record in page.records}

    # Only the requested billing account's rows are present: the fixture's
    # third row belongs to a different account and must not leak in.
    assert set(records) == {
        "gcp:gcp-billing-acct-1:gcp-billing-acct-1:sku-n1-core-us:2026-10-01T00:00:00+00:00:2026-10-01T01:00:00+00:00",
        "gcp:gcp-billing-acct-1:gcp-billing-acct-1:sku-standard-storage:2026-10-01T00:00:00+00:00:2026-10-02T00:00:00+00:00",
    }

    compute = records[
        "gcp:gcp-billing-acct-1:gcp-billing-acct-1:sku-n1-core-us:2026-10-01T00:00:00+00:00:2026-10-01T01:00:00+00:00"
    ]
    assert compute.tenant_id == TENANT
    assert compute.project_id == PROJECT
    assert compute.provider == "gcp"
    assert compute.account_id == ACCOUNT
    assert compute.service == "Compute Engine"
    assert compute.region == "us-central1"
    assert compute.period_start == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert compute.period_end == datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    assert compute.currency == "USD"
    assert compute.amount_minor == 1234
    assert compute.tags == {"env": "prod", "team": "platform"}
    assert compute.provenance.source_system == "gcp"
    assert compute.provenance.parser_version == "r1-11-gcp-billing-1"
    assert compute.provenance.ingest_run_id == "conn-billing-1"
    assert compute.provenance.ingested_at == NOW
    assert compute.provenance.observed_at == compute.period_end
    assert compute.provenance.raw_ref.startswith("gcp://gcp-billing-acct-1/billing/")

    storage = records[
        "gcp:gcp-billing-acct-1:gcp-billing-acct-1:sku-standard-storage:2026-10-01T00:00:00+00:00:2026-10-02T00:00:00+00:00"
    ]
    assert storage.region == "us"
    assert storage.amount_minor == 46  # 0.456 rounded half-up to the cent
    assert storage.tags == {"env": "prod"}

    assert page.coverage.observed_services == ("Cloud Storage", "Compute Engine")


def test_billing_rows_outside_the_requested_period_are_excluded() -> None:
    adapter = _adapter("golden.json")
    request = BillingRequest(
        connection=_connection(),
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 2, 1, tzinfo=UTC),
    )
    page = adapter.read_billing(request)
    assert page.records == ()


def test_missing_tags_import_cleanly_with_empty_tags_visible() -> None:
    adapter = _adapter("missing_tags.json")
    request = BillingRequest(
        connection=_connection(account_id="gcp-billing-acct-2"),
        period_start=datetime(2026, 9, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 1, tzinfo=UTC),
    )
    page = adapter.read_billing(request)

    # Both rows import -- the one with no "tags" key at all is not dropped.
    assert len(page.records) == 2
    for record in page.records:
        assert record.tags == {}
    assert {record.service for record in page.records} == {
        "Compute Engine",
        "Cloud Storage",
    }


def test_gcp_billing_adapter_satisfies_the_billing_contract() -> None:
    adapter = _adapter("golden.json")
    ids = assert_billing_contract(adapter, _request(page_size=1))
    assert len(ids) == 2


def test_gcp_billing_adapter_refuses_when_connection_provider_does_not_match() -> None:
    adapter = _adapter("golden.json")
    other = ProviderConnection(
        connection_id="conn-billing-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="aws",
        account_id=ACCOUNT,
        credential_ref="secret://aws/conn-billing-1",
    )
    request = BillingRequest(
        connection=other,
        period_start=datetime(2026, 9, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        adapter.read_billing(request)


def test_gcp_billing_file_source_rejects_a_non_json_file(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")
    adapter = GcpBillingAdapter(source=GcpBillingFileSource(path=bad_file), clock=lambda: NOW)
    with pytest.raises(ValidationError):
        adapter.read_billing(_request())
