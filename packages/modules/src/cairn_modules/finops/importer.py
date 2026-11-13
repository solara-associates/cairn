"""R1-11: canonicalize billing line items into ``CostRecord``s.

This is the one place that decides what a canonical cost record looks like:
every record carries its currency, billing period, resource tags (empty,
never omitted, when the source row carried none), and full provenance back
to the originating export row. A provider adapter supplies ``BillingLineItem``s
already shaped for its own export format; this module does not know GCP,
AWS, or Azure exist.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from cairn_contracts.estate import CostRecord, Provenance

from cairn_modules.finops.model import BillingLineItem


def to_cost_record(
    item: BillingLineItem,
    *,
    ingest_run_id: str,
    parser_version: str,
    ingested_at: datetime,
) -> CostRecord:
    """Turn one ``BillingLineItem`` into its canonical ``CostRecord``.

    ``tags`` is carried through verbatim -- including empty -- so a row
    with no tags produces a record whose tags are visibly ``{}`` rather
    than being dropped or defaulted away.
    """

    cost_id = f"{item.provider}:{item.account_id}:{item.source_id}"
    return CostRecord(
        cost_id=cost_id,
        tenant_id=item.tenant_id,
        project_id=item.project_id,
        provider=item.provider,
        account_id=item.account_id,
        service=item.service,
        region=item.region,
        period_start=item.period_start,
        period_end=item.period_end,
        currency=item.currency,
        amount_minor=item.amount_minor,
        tags=dict(item.tags),
        provenance=Provenance(
            source_system=item.provider,
            source_id=item.source_id,
            source_version=item.source_version,
            observed_at=item.period_end,
            ingested_at=ingested_at,
            parser_version=parser_version,
            ingest_run_id=ingest_run_id,
            raw_ref=item.raw_ref,
        ),
    )


def import_cost_records(
    items: Iterable[BillingLineItem],
    *,
    ingest_run_id: str,
    parser_version: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[CostRecord, ...]:
    """Canonicalize a batch of billing line items in one import run.

    Every record in the batch is stamped with the same ``ingested_at``
    moment, since they were all produced by the same import run.
    """

    ingested_at = clock()
    return tuple(
        to_cost_record(
            item,
            ingest_run_id=ingest_run_id,
            parser_version=parser_version,
            ingested_at=ingested_at,
        )
        for item in items
    )


__all__ = ["import_cost_records", "to_cost_record"]
