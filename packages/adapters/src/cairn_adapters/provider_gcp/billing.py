"""R1-11: a GCP billing import adapter, built on top of R1-05's provider.

GCP's standard billing export (to BigQuery or a flat file) is a sequence of
line-item rows, each naming a service, a SKU, a usage window, a cost, a
currency, and optional resource tags/labels. This module reads that export
-- a fixture file in tests, never a live GCP call -- and canonicalizes each
row into a ``cairn_contracts.estate.CostRecord`` via ``cairn_modules.finops``.

The row shape this parses (``_parse_row`` below) mirrors GCP's real export
schema closely enough to exercise the same fields a live export would
carry: ``billing_account_id``, nested ``service``/``sku``/``project``/
``location`` objects, ``usage_start_time``/``usage_end_time``, ``cost``,
``currency``, and a ``tags`` list of ``{"key": ..., "value": ...}`` pairs.
Parsing that shape is GCP-specific plumbing; deciding what a canonical cost
record looks like (currency, period, tags, provenance) is not -- that logic
lives in ``cairn_modules.finops`` and is shared with every other provider.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol

from cairn_kernel.errors import ValidationError
from cairn_modules.finops import BillingLineItem, import_cost_records

from cairn_adapters.provider_core.ports import (
    BillingPage,
    BillingRequest,
    CoverageReport,
    ProviderCapability,
    ProviderConnection,
    ProviderDescriptor,
)

PROVIDER = "gcp"
PARSER_VERSION = "r1-11-gcp-billing-1"
_MAX_GCP_BILLING_PAGES = 1_000


class GcpBillingExportSource(Protocol):
    """The outbound port a billing adapter reads export rows through."""

    def read_rows(self, billing_account_id: str) -> Sequence[Mapping[str, object]]: ...


@dataclass(frozen=True, slots=True)
class GcpBillingFileSource:
    """A ``GcpBillingExportSource`` backed by a JSON export file.

    The file holds a JSON array of export rows (the shape GCP's BigQuery
    billing export table would be read from); every row is returned
    regardless of ``billing_account_id`` filtering performed by the
    adapter, except that only rows whose own ``billing_account_id`` match
    the requested one are returned -- a file may hold more than one
    account's export, as a real export table does.
    """

    path: Path

    def read_rows(self, billing_account_id: str) -> Sequence[Mapping[str, object]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"gcp billing export file could not be read: {exc}") from exc
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"gcp billing export file is not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            raise ValidationError("gcp billing export file must contain a JSON array")
        return tuple(
            row
            for row in rows
            if isinstance(row, dict) and row.get("billing_account_id") == billing_account_id
        )


@dataclass(frozen=True, slots=True)
class GcpBillingAdapter:
    """Implements provider-core's ``BillingSourcePort`` for GCP."""

    source: GcpBillingExportSource
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider=PROVIDER,
            display_name="Google Cloud Platform",
            capabilities=frozenset({ProviderCapability.BILLING}),
        )

    def read_billing(self, request: BillingRequest) -> BillingPage:
        connection = request.connection
        if connection.provider != PROVIDER:
            raise ValidationError(
                f"connection provider {connection.provider} is not {PROVIDER}"
            )
        rows = self.source.read_rows(connection.account_id)
        items = tuple(_parse_row(row, connection) for row in rows)
        in_period = tuple(
            item
            for item in items
            if item.period_start < request.period_end
            and item.period_end > request.period_start
        )
        records = import_cost_records(
            in_period,
            ingest_run_id=connection.connection_id,
            parser_version=PARSER_VERSION,
            clock=self.clock,
        )
        records = tuple(sorted(records, key=lambda record: record.cost_id))
        page, next_cursor = _offset_page(records, request.cursor, request.page_size)
        observed = tuple(sorted({record.service for record in records}))
        return BillingPage(
            records=page,
            next_cursor=next_cursor,
            coverage=CoverageReport(observed_services=observed),
            observed_at=self.clock(),
        )


def _parse_row(row: Mapping[str, object], connection: ProviderConnection) -> BillingLineItem:
    service = _nested(row, "service", "description")
    sku_id = _nested(row, "sku", "id")
    usage_start = _parse_timestamp(row, "usage_start_time")
    usage_end = _parse_timestamp(row, "usage_end_time")
    region = _nested(row, "location", "region") or _nested(row, "location", "location")
    if not region:
        region = "global"
    currency = row.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValidationError("gcp billing row is missing a currency")
    amount_minor = _amount_minor(row.get("cost"))
    tags = _parse_tags(row.get("tags"))
    source_id = f"{connection.account_id}:{sku_id}:{usage_start.isoformat()}:{usage_end.isoformat()}"
    return BillingLineItem(
        source_id=source_id,
        provider=PROVIDER,
        tenant_id=connection.tenant_id,
        project_id=connection.project_id,
        account_id=connection.account_id,
        service=str(service),
        region=str(region),
        period_start=usage_start,
        period_end=usage_end,
        currency=currency,
        amount_minor=amount_minor,
        tags=tags,
        raw_ref=f"gcp://{connection.account_id}/billing/{source_id}",
    )


def _nested(row: Mapping[str, object], outer: str, inner: str) -> str | None:
    value = row.get(outer)
    if not isinstance(value, Mapping):
        return None
    nested = value.get(inner)
    return str(nested) if nested is not None else None


def _parse_timestamp(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"gcp billing row is missing {key}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"gcp billing row {key} is not a valid timestamp") from exc


def _amount_minor(cost: object) -> int:
    if cost is None or isinstance(cost, bool):
        raise ValidationError("gcp billing row is missing a cost")
    try:
        decimal_cost = Decimal(str(cost))
    except (ArithmeticError, ValueError) as exc:
        raise ValidationError("gcp billing row cost is not numeric") from exc
    minor = (decimal_cost * 100).to_integral_value(rounding=ROUND_HALF_UP)
    return int(minor)


def _parse_tags(raw_tags: object) -> dict[str, str]:
    if not raw_tags:
        return {}
    if not isinstance(raw_tags, list):
        raise ValidationError("gcp billing row tags must be a list")
    tags: dict[str, str] = {}
    for entry in raw_tags:
        if not isinstance(entry, Mapping) or "key" not in entry or "value" not in entry:
            raise ValidationError("gcp billing row tag entries need a key and a value")
        tags[str(entry["key"])] = str(entry["value"])
    return tags


def _offset_page(
    items: Sequence[object], cursor: str | None, page_size: int
) -> tuple[tuple[object, ...], str | None]:
    if cursor is None:
        offset = 0
    else:
        try:
            offset = int(cursor)
        except ValueError as exc:
            raise ValidationError("gcp billing cursor is not valid") from exc
        if offset < 0 or offset > len(items):
            raise ValidationError("gcp billing cursor is out of range")
    page = tuple(items[offset : offset + page_size])
    end = offset + len(page)
    next_cursor = None if end >= len(items) else str(end)
    return page, next_cursor


__all__ = ["GcpBillingAdapter", "GcpBillingExportSource", "GcpBillingFileSource"]
