from pathlib import Path

from cairn_kits.vertical_packs.harness import (
    DOMAIN_PURITY_CHECK,
    MANIFEST_CHECK,
    SMOKE_TEST_CHECK,
    run_conformance,
)
from cairn_kits.vertical_packs.manifest import PackManifest, validate_manifest_fields

FIXTURES = Path(__file__).parent / "fixtures"


def test_accepts_a_minimal_conformant_pack() -> None:
    report = run_conformance("good_pack", FIXTURES)

    assert report.passed, report.results
    assert report.failed_checks == ()


def test_rejects_a_pack_missing_its_manifest() -> None:
    report = run_conformance("bad_pack_missing_manifest", FIXTURES)

    assert not report.passed
    # Named rejection, not a generic failure: exactly the manifest check.
    assert report.failed_checks == (MANIFEST_CHECK,)
    assert "manifest" in report.detail_for(MANIFEST_CHECK)


def test_rejects_a_pack_that_violates_domain_purity() -> None:
    report = run_conformance("bad_pack_violation", FIXTURES)

    assert not report.passed
    # Named rejection: domain-purity specifically, naming the offending import.
    assert DOMAIN_PURITY_CHECK in report.failed_checks
    detail = report.detail_for(DOMAIN_PURITY_CHECK)
    assert "cairn_adapters" in detail
    # Its manifest and smoke test are otherwise valid.
    assert MANIFEST_CHECK not in report.failed_checks
    assert SMOKE_TEST_CHECK not in report.failed_checks


def test_manifest_requires_non_empty_pack_id_and_version() -> None:
    manifest = PackManifest(pack_id="", version="")

    errors = validate_manifest_fields(manifest)

    assert any("pack_id" in error for error in errors)
    assert any("version" in error for error in errors)


def test_manifest_requires_mutation_classes_from_the_kernel_enum() -> None:
    manifest = PackManifest(
        pack_id="pack",
        version="0.1.0",
        declared_mutation_classes=("not-a-mutation-class",),  # type: ignore[arg-type]
    )

    errors = validate_manifest_fields(manifest)

    assert any("declared_mutation_classes" in error for error in errors)
