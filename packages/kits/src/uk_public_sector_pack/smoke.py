"""Smoke test for the UK public sector pack.

The synthetic ``good_pack`` fixture's own smoke test only asserts its own
manifest's fields (``cairn_kits.vertical_packs.conventions``'s own
docstring is explicit that fixture is the harness's positive control, not a
real pack). This is the real pack, so this smoke test proves two things
that are actually true about the wider codebase, not just about this
file:

1. The pattern this pack is built on (``landing-zone``) is a real, loadable
   entry in R2-03's own published catalogue seed
   (``patterns/landing-zone.yaml`` at the repo root) -- not a string this
   pack invented.
2. The residency constraint this pack is built on is wired to R5-05b's own
   sweep for real: feeding it a tiny two-workload fixture (one inside the
   UK's allowed region, one outside it) -- reusing the exact
   fixture-building shape
   ``packages/modules/tests/test_residency_sweep.py`` already uses, not a
   new fixture style -- produces exactly the finding a UK public sector
   pack needs it to produce: the out-of-region workload flagged, the
   in-region workload clean.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_contracts.estate.model import FactStatus, FactValue, Workload
from cairn_contracts.mapping.pattern import PatternCategory
from cairn_modules.design.patterns import load_pattern
from cairn_modules.sovereignty.residency_sweep import (
    REGION_FACT_KEY,
    UK_ALLOWED_REGIONS,
    ResidencyFindingReason,
    ResidencySweepStatus,
    sweep_estate_residency,
)

# This file lives at packages/kits/src/uk_public_sector_pack/smoke.py --
# parents[4] is the repo root, the same "walk up from __file__" convention
# packages/modules/tests/test_pattern_catalogue.py already uses to find
# patterns/ at the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_LANDING_ZONE_PATTERN_PATH = _REPO_ROOT / "patterns" / "landing-zone.yaml"

_MOMENT = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)


def _region_fact(value: str) -> FactValue:
    return FactValue(
        value=value,
        status=FactStatus.OBSERVED,
        source="uk-public-sector-pack-smoke-test",
        observed_at=_MOMENT,
        ingested_at=_MOMENT,
        confidence=None,
        mapping_version=None,
        provenance_ref="uk-public-sector-pack-smoke-test#0",
    )


def _workload(workload_id: str, *, region: str) -> Workload:
    return Workload(
        workload_id=workload_id,
        tenant_id="smoke-tenant",
        project_id="smoke-project",
        name=workload_id,
        environment="prod",
        owner=None,
        business_context=None,
        resource_ids=(),
        dependency_ids=(),
        facts={REGION_FACT_KEY: _region_fact(region)},
        disposition=None,
        disposition_confidence=None,
        model_version="uk-public-sector-pack-smoke-v1",
        mapping_version="uk-public-sector-pack-smoke-v1",
    )


def run_smoke_test() -> None:
    """Prove the pack's declared ports resolve to real, live behaviour."""
    from uk_public_sector_pack.manifest import MANIFEST

    assert MANIFEST.pack_id == "uk-public-sector"

    # 1. The landing-zone pattern this pack is built on genuinely exists in
    # R2-03's own published catalogue seed.
    pattern = load_pattern(_LANDING_ZONE_PATTERN_PATH)
    assert pattern.id == "landing-zone"
    assert pattern.category is PatternCategory.LANDING_ZONE

    # 2. The residency constraint this pack is built on is wired to
    # R5-05b's own sweep, for real, against a UK-in-region and an
    # out-of-region workload.
    allowed_region = next(iter(sorted(UK_ALLOWED_REGIONS)))
    in_region = _workload("uk-public-sector-smoke-in-region", region=allowed_region)
    out_of_region = _workload("uk-public-sector-smoke-out-of-region", region="us-east1")

    result = sweep_estate_residency([in_region, out_of_region])

    assert result.status is ResidencySweepStatus.FINDINGS
    assert result.workloads_checked == 2
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.workload_id == out_of_region.workload_id
    assert finding.reason is ResidencyFindingReason.OUT_OF_REGION
