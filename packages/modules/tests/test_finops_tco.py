"""Tests for R1-13 TCO scenario engine with assumptions and price timestamp.

Covers the acceptance criterion: "Assumptions explicit; reproducible
result."

- reproducibility: the same baseline, assumptions and price-list
  version produce an identical result, run twice;
- assumptions-visibility: every assumption is recorded on the result,
  along with the exact price-list version and release timestamp used;
- price-list immutability: a republish of the same version with
  different content is rejected (R0-14's mechanism, reused as-is).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.finops import PriceListRelease
from cairn_kernel.errors import PriceListUnavailableError, ValidationError
from cairn_modules.finops import (
    BillingLineItem,
    InMemoryPriceList,
    TcoAssumptions,
    build_baseline,
    compute_tco,
    import_cost_records,
    load_price_list_release,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = REPO_ROOT / "pricing" / "gcp-price-list-seed.yaml"

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
        "region": "europe-west2",
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "currency": "GBP",
        "amount_minor": 100_000,
        "tags": {"env": "prod"},
        "raw_ref": "gcp://acct/billing/row-1",
    }
    fields.update(overrides)
    return BillingLineItem(**fields)


def _baseline():
    records = import_cost_records(
        [_line_item()], ingest_run_id="run-1", parser_version="test-1"
    )
    return build_baseline(records, currency="GBP")


def _price_list() -> PriceListRelease:
    return load_price_list_release(SEED_PATH)


def _assumptions(**overrides: object) -> TcoAssumptions:
    fields: dict = {"horizon_periods": 3, "growth_rate": 0.02, "discount_rate": 0.1}
    fields.update(overrides)
    return TcoAssumptions(**fields)


# --- reproducibility ----------------------------------------------------------


def test_same_inputs_produce_an_identical_result_every_run() -> None:
    baseline = _baseline()
    assumptions = _assumptions()
    price_list = _price_list()

    first = compute_tco(baseline, assumptions, price_list, scenario_id="scenario-1")
    second = compute_tco(baseline, assumptions, price_list, scenario_id="scenario-1")

    assert first == second
    assert first.period_amounts_minor == second.period_amounts_minor


def test_different_assumptions_change_the_result() -> None:
    baseline = _baseline()
    price_list = _price_list()

    low_growth = compute_tco(baseline, _assumptions(growth_rate=0.0), price_list, scenario_id="s")
    high_growth = compute_tco(baseline, _assumptions(growth_rate=0.5), price_list, scenario_id="s")

    assert low_growth.projected_total_minor != high_growth.projected_total_minor


# --- assumptions are explicit, price timestamp is recorded ------------------


def test_result_records_every_assumption_and_the_exact_price_list_used() -> None:
    baseline = _baseline()
    assumptions = _assumptions(horizon_periods=4, growth_rate=0.03, discount_rate=0.15)
    price_list = _price_list()

    result = compute_tco(baseline, assumptions, price_list, scenario_id="scenario-1")

    assert result.assumptions.horizon_periods == 4
    assert result.assumptions.growth_rate == 0.03
    assert result.assumptions.discount_rate == 0.15
    assert result.price_list_version == price_list.version
    assert result.price_list_released_at == price_list.released_at
    assert len(result.period_amounts_minor) == 4
    assert result.projected_total_minor == sum(result.period_amounts_minor)


@pytest.mark.parametrize(
    "overrides",
    [
        {"horizon_periods": 0},
        {"growth_rate": -1.0},
        {"discount_rate": 1.0},
        {"discount_rate": -0.1},
    ],
)
def test_assumptions_reject_nonsensical_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _assumptions(**overrides)


# --- price-list immutability (R0-14's mechanism, reused) --------------------


def test_price_list_release_loads_from_the_seed() -> None:
    release = _price_list()
    assert release.version == "2026.11.1"
    assert len(release.entries) == 3


def test_price_list_registry_rejects_a_changed_republish_of_the_same_version() -> None:
    registry = InMemoryPriceList()
    original = _price_list()
    registry.publish(original)

    payload = original.model_dump(mode="json")
    payload["entries"][0]["unit_price_minor"] = 999999
    changed = PriceListRelease.model_validate(payload)

    with pytest.raises(ValidationError, match="immutable"):
        registry.publish(changed)


def test_unknown_price_list_version_is_unavailable() -> None:
    registry = InMemoryPriceList()
    registry.publish(_price_list())

    with pytest.raises(PriceListUnavailableError):
        registry.get("2099.01.1")
