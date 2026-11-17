"""R5-06b: the real UK public sector pack, run through 822's own harness.

Two things are proven here:

1. The harness's acceptance criteria actually extend to a real,
   non-synthetic pack -- not just the harness's own synthetic fixtures
   (``good_pack``/``bad_pack_*``). ``uk_public_sector_pack`` lives under
   ``packages/kits/src``, is a standalone top-level package (see its own
   ``__init__.py`` for why it is not nested inside ``cairn_kits``), and
   passes ``run_conformance`` end to end.
2. A second, deliberately broken variant of that same real pack
   (``uk_public_sector_pack_broken``, reusing 822's own
   ``bad_pack_violation`` break style: a direct adapter import) is
   rejected by the same harness run.
"""

from __future__ import annotations

from pathlib import Path

from cairn_kits.vertical_packs.harness import (
    DOMAIN_PURITY_CHECK,
    MANIFEST_CHECK,
    SMOKE_TEST_CHECK,
    run_conformance,
)

PACK_SRC_ROOT = Path(__file__).parents[1] / "src"
FIXTURES = Path(__file__).parent / "fixtures"


def test_real_uk_public_sector_pack_passes_the_harness() -> None:
    report = run_conformance("uk_public_sector_pack", PACK_SRC_ROOT)

    assert report.passed, report.results
    assert report.failed_checks == ()


def test_broken_variant_is_rejected_for_domain_purity() -> None:
    report = run_conformance("uk_public_sector_pack_broken", FIXTURES)

    assert not report.passed
    assert DOMAIN_PURITY_CHECK in report.failed_checks
    detail = report.detail_for(DOMAIN_PURITY_CHECK)
    assert "cairn_adapters" in detail
    # Its manifest and smoke test are otherwise valid -- the violation is
    # named specifically, not masked by an unrelated failure.
    assert MANIFEST_CHECK not in report.failed_checks
    assert SMOKE_TEST_CHECK not in report.failed_checks
