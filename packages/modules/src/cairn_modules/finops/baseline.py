"""R1-12: cost baseline and coverage/unallocated spend.

Builds a cost baseline from R1-11's canonical ``CostRecord``\\ s. At this
story, the only attribution signal a cost record carries is its own
``tags`` -- R1-07's workload linkage doesn't exist in this story's
dependency boundary (R1-12 depends only on R1-11), so a record with at
least one tag is "attributable" and a record with none is "unallocated."
An unallocated record is never excluded from the total -- it is shown
explicitly, by cost id, alongside it.

Because "missing tags" is exactly what makes a record unallocated here,
the missing-tag report and the unallocated set name the same records;
they are kept as distinct, separately named outputs because the
acceptance criterion calls for both ("coverage shown; missing tags
reported") and a future story wiring in real workload attribution
(R1-14/R1-15) will make them diverge -- a record could then be
attributable by workload linkage despite having no tags, or vice versa.

A baseline covers one currency. Records are grouped by currency before
aggregation -- summing minor units across different currencies would
silently misstate the total, so :func:`build_baselines` never does it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from cairn_contracts.estate import CostRecord


@dataclass(frozen=True, slots=True)
class CostBaseline:
    """The cost baseline for one currency's worth of records."""

    currency: str
    total_amount_minor: int
    attributable_amount_minor: int
    unallocated_amount_minor: int
    attributable_cost_ids: tuple[str, ...]
    unallocated_cost_ids: tuple[str, ...]
    missing_tag_cost_ids: tuple[str, ...]

    @property
    def record_count(self) -> int:
        return len(self.attributable_cost_ids) + len(self.unallocated_cost_ids)


def _is_attributable(record: CostRecord) -> bool:
    return bool(record.tags)


def build_baseline(records: Sequence[CostRecord], *, currency: str) -> CostBaseline:
    """Build the baseline for exactly one ``currency``'s records.

    Raises ``ValueError`` if any record carries a different currency --
    callers that may have a mixed-currency batch should use
    :func:`build_baselines` instead, which groups by currency first.
    """
    for record in records:
        if record.currency != currency:
            raise ValueError(
                f"cost record {record.cost_id} is {record.currency}, not {currency} -- "
                "group by currency before building a single-currency baseline"
            )

    attributable = tuple(sorted(r.cost_id for r in records if _is_attributable(r)))
    unallocated = tuple(sorted(r.cost_id for r in records if not _is_attributable(r)))
    by_id = {r.cost_id: r for r in records}

    return CostBaseline(
        currency=currency,
        total_amount_minor=sum(r.amount_minor for r in records),
        attributable_amount_minor=sum(by_id[cost_id].amount_minor for cost_id in attributable),
        unallocated_amount_minor=sum(by_id[cost_id].amount_minor for cost_id in unallocated),
        attributable_cost_ids=attributable,
        unallocated_cost_ids=unallocated,
        missing_tag_cost_ids=unallocated,
    )


def build_baselines(records: Sequence[CostRecord]) -> tuple[CostBaseline, ...]:
    """Group ``records`` by currency and build one baseline per currency."""
    by_currency: dict[str, list[CostRecord]] = defaultdict(list)
    for record in records:
        by_currency[record.currency].append(record)

    return tuple(
        build_baseline(by_currency[currency], currency=currency) for currency in sorted(by_currency)
    )


__all__ = ["CostBaseline", "build_baseline", "build_baselines"]
