"""R1-13: TCO scenario engine with explicit assumptions and price timestamp.

Projects an R1-12 cost baseline forward over an explicit horizon using
named, recorded assumptions (growth rate, discount rate) -- never a
hidden default -- and references the exact price-list version and
release timestamp used, so the same inputs plus the same price-list
version always reproduce the identical result (``compute_tco`` is a
pure function of its arguments: no clock, no randomness, no mutable
state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cairn_contracts.finops import PriceListRelease

from cairn_modules.finops.baseline import CostBaseline


@dataclass(frozen=True, slots=True)
class TcoAssumptions:
    """Every assumption a TCO projection depends on, named and explicit."""

    horizon_periods: int
    growth_rate: float
    discount_rate: float

    def __post_init__(self) -> None:
        if self.horizon_periods < 1:
            raise ValueError("horizon_periods must be at least 1")
        if not -1.0 < self.growth_rate:
            raise ValueError("growth_rate cannot reduce a period's cost below zero")
        if not 0.0 <= self.discount_rate < 1.0:
            raise ValueError("discount_rate must be in [0.0, 1.0)")


@dataclass(frozen=True, slots=True)
class TcoResult:
    """One reproducible TCO projection, with every input it depended on."""

    scenario_id: str
    currency: str
    baseline_total_minor: int
    assumptions: TcoAssumptions
    price_list_version: str
    price_list_released_at: datetime
    period_amounts_minor: tuple[int, ...]
    projected_total_minor: int


def compute_tco(
    baseline: CostBaseline,
    assumptions: TcoAssumptions,
    price_list: PriceListRelease,
    *,
    scenario_id: str,
) -> TcoResult:
    """Project ``baseline`` forward under ``assumptions``.

    Each period's cost is the baseline total, discounted once by
    ``assumptions.discount_rate`` and compounded by
    ``assumptions.growth_rate`` for that period number -- a plain,
    explicit formula with no hidden tuning, so the same three
    assumptions always produce the same periods.
    """
    discounted_base = baseline.total_amount_minor * (1 - assumptions.discount_rate)
    periods = tuple(
        round(discounted_base * (1 + assumptions.growth_rate) ** period)
        for period in range(1, assumptions.horizon_periods + 1)
    )

    return TcoResult(
        scenario_id=scenario_id,
        currency=baseline.currency,
        baseline_total_minor=baseline.total_amount_minor,
        assumptions=assumptions,
        price_list_version=price_list.version,
        price_list_released_at=price_list.released_at,
        period_amounts_minor=periods,
        projected_total_minor=sum(periods),
    )


__all__ = ["TcoAssumptions", "TcoResult", "compute_tco"]
