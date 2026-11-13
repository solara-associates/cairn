"""Tests for the R1-09 scanner adapters (Prowler, Steampipe, OPA).

Each scanner gets a golden-fixture test (exact normalized ``Finding``
output, referencing the R1-08 control version) and an unsupported-record
test (every unmappable/malformed record is reported, not dropped).
Fixtures live under ``tests/fixtures/scanners/`` at the repository root.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_adapters.scanners import opa_adapter, prowler_adapter, steampipe_adapter
from cairn_contracts.posture import ControlVersionReference
from cairn_kernel.errors import ValidationError
from cairn_modules.posture.findings import Finding, FindingStatus

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scanners"
MOMENT = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
RELEASE_VERSION = "2026.11.1"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_fixtures_directory_exists() -> None:
    assert FIXTURES.is_dir(), f"expected fixtures at {FIXTURES}"


# --- Prowler -----------------------------------------------------------------


def test_prowler_golden_fixture_parses_exactly() -> None:
    result = prowler_adapter.parse(
        _load("golden.prowler.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.scanner == "prowler"
    assert result.parser_version == prowler_adapter.PARSER_VERSION
    assert result.finding_count == 2
    assert result.unsupported_count == 0

    assert result.findings[0].scanner_check_id == "iam_corporate_login_credentials"
    assert result.findings[0].status is FindingStatus.FAIL
    assert result.findings[0].control_reference == ControlVersionReference(
        control_id="gcp-cis-1.1", release_version=RELEASE_VERSION
    )
    assert result.findings[0].resource_id == "projects/my-project-1"
    assert result.findings[0].resource_type == "Project"
    assert result.findings[0].observed_at == MOMENT

    assert result.findings[1].scanner_check_id == "iam_user_managed_service_account_key"
    assert result.findings[1].status is FindingStatus.PASS
    assert result.findings[1].control_reference == ControlVersionReference(
        control_id="gcp-cis-1.4", release_version=RELEASE_VERSION
    )


def test_prowler_unsupported_records_are_reported_not_dropped() -> None:
    result = prowler_adapter.parse(
        _load("unsupported.prowler.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.finding_count == 0
    assert result.unsupported_count == 3
    assert result.record_count == 3

    reasons = [u.reason for u in result.unsupported]
    assert any("storage_unknown_check_xyz" in r for r in reasons)
    assert any("NOTAPPLICABLE" in r for r in reasons)
    assert any("not a JSON object" in r for r in reasons)


def test_prowler_invalid_json_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        prowler_adapter.parse("{not valid json", release_version=RELEASE_VERSION)


def test_prowler_non_array_top_level_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        prowler_adapter.parse('{"not": "an array"}', release_version=RELEASE_VERSION)


# --- Steampipe ---------------------------------------------------------------


def test_steampipe_golden_fixture_parses_exactly() -> None:
    result = steampipe_adapter.parse(
        _load("golden.steampipe.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.scanner == "steampipe"
    assert result.parser_version == steampipe_adapter.PARSER_VERSION
    assert result.finding_count == 2
    assert result.unsupported_count == 0

    assert result.findings[0].scanner_check_id == "gcp_cis_v200.control.cis_v200_3_1"
    assert result.findings[0].status is FindingStatus.FAIL
    assert result.findings[0].control_reference == ControlVersionReference(
        control_id="gcp-cis-3.1", release_version=RELEASE_VERSION
    )
    assert result.findings[0].resource_id == "projects/my-project-1/global/networks/default"

    assert result.findings[1].scanner_check_id == "gcp_cis_v200.control.cis_v200_3_6"
    assert result.findings[1].status is FindingStatus.PASS
    assert result.findings[1].control_reference == ControlVersionReference(
        control_id="gcp-cis-3.6", release_version=RELEASE_VERSION
    )


def test_steampipe_unsupported_records_are_reported_not_dropped() -> None:
    result = steampipe_adapter.parse(
        _load("unsupported.steampipe.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.finding_count == 0
    assert result.unsupported_count == 3
    assert result.record_count == 3

    reasons = [u.reason for u in result.unsupported]
    assert any("cis_v200_7_9" in r for r in reasons)
    assert any("'error'" in r for r in reasons)
    assert any("'results'" in r for r in reasons)


def test_steampipe_invalid_json_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        steampipe_adapter.parse("{not valid json", release_version=RELEASE_VERSION)


def test_steampipe_non_object_top_level_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        steampipe_adapter.parse("[]", release_version=RELEASE_VERSION)


# --- OPA -----------------------------------------------------------------------


def test_opa_golden_fixture_parses_exactly() -> None:
    result = opa_adapter.parse(
        _load("golden.opa.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.scanner == "opa"
    assert result.parser_version == opa_adapter.PARSER_VERSION
    assert result.finding_count == 2
    assert result.unsupported_count == 0

    assert result.findings[0].scanner_check_id == "cis_5_1"
    assert result.findings[0].status is FindingStatus.FAIL
    assert result.findings[0].control_reference == ControlVersionReference(
        control_id="gcp-cis-5.1", release_version=RELEASE_VERSION
    )
    assert result.findings[0].resource_id == "projects/my-project-1/buckets/public-bucket"

    assert result.findings[1].scanner_check_id == "cis_6_1"
    assert result.findings[1].status is FindingStatus.PASS
    assert result.findings[1].control_reference == ControlVersionReference(
        control_id="gcp-cis-6.1", release_version=RELEASE_VERSION
    )


def test_opa_unsupported_records_are_reported_not_dropped() -> None:
    result = opa_adapter.parse(
        _load("unsupported.opa.json"), release_version=RELEASE_VERSION, observed_at=MOMENT
    )

    assert result.finding_count == 0
    assert result.unsupported_count == 3
    assert result.record_count == 3

    reasons = [u.reason for u in result.unsupported]
    assert any("cis_9_9" in r for r in reasons)
    assert any("'allow'" in r for r in reasons)
    assert any("not a JSON object" in r for r in reasons)


def test_opa_invalid_json_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        opa_adapter.parse("{not valid json", release_version=RELEASE_VERSION)


def test_opa_missing_result_envelope_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        opa_adapter.parse('{"result": []}', release_version=RELEASE_VERSION)


# --- cross-scanner -------------------------------------------------------------


def test_parser_versions_are_distinct_per_scanner() -> None:
    versions = {
        prowler_adapter.PARSER_VERSION,
        steampipe_adapter.PARSER_VERSION,
        opa_adapter.PARSER_VERSION,
    }
    assert len(versions) == 3


def test_finding_raw_is_immutable() -> None:
    result = prowler_adapter.parse(_load("golden.prowler.json"), release_version=RELEASE_VERSION)
    finding = result.findings[0]
    assert isinstance(finding, Finding)
    with pytest.raises(TypeError):
        finding.raw["CheckID"] = "changed"  # type: ignore[index]
