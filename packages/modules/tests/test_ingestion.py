"""Tests for the R1-03 file ingestion adapters.

Each format gets a golden-fixture test (exact parsed output, including the
recorded parser version) and a malformed-fixture test (a clean
``ValidationError``, not a crash). Fixtures live under
``tests/fixtures/ingestion/`` at the repository root.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_kernel.errors import ValidationError
from cairn_modules.ingestion import (
    bom_adapter,
    csv_adapter,
    hvtools_adapter,
    json_adapter,
    rvtools_adapter,
)
from cairn_modules.ingestion.models import RawObservation

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ingestion"
MOMENT = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_fixtures_directory_exists() -> None:
    assert FIXTURES.is_dir(), f"expected fixtures at {FIXTURES}"


# --- CSV -------------------------------------------------------------------


def test_csv_golden_fixture_parses_exactly() -> None:
    result = csv_adapter.parse(_load("golden.csv"), observed_at=MOMENT)

    assert result.source_format == "csv"
    assert result.parser_version == csv_adapter.PARSER_VERSION
    assert result.record_count == 2
    assert result.observations == (
        RawObservation(
            source_format="csv",
            parser_version=csv_adapter.PARSER_VERSION,
            record_index=0,
            fields={"hostname": "web-01", "ip_address": "10.0.1.10", "role": "web"},
            observed_at=MOMENT,
        ),
        RawObservation(
            source_format="csv",
            parser_version=csv_adapter.PARSER_VERSION,
            record_index=1,
            fields={"hostname": "db-01", "ip_address": "10.0.1.20", "role": None},
            observed_at=MOMENT,
        ),
    )


def test_csv_malformed_fixture_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        csv_adapter.parse(_load("malformed.csv"))


def test_csv_empty_file_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        csv_adapter.parse("")


# --- JSON --------------------------------------------------------------------


def test_json_golden_fixture_parses_exactly() -> None:
    result = json_adapter.parse(_load("golden.json"), observed_at=MOMENT)

    assert result.source_format == "json"
    assert result.parser_version == json_adapter.PARSER_VERSION
    assert result.record_count == 2
    assert result.observations == (
        RawObservation(
            source_format="json",
            parser_version=json_adapter.PARSER_VERSION,
            record_index=0,
            fields={"hostname": "web-01", "ip_address": "10.0.1.10", "role": "web"},
            observed_at=MOMENT,
        ),
        RawObservation(
            source_format="json",
            parser_version=json_adapter.PARSER_VERSION,
            record_index=1,
            fields={"hostname": "db-01", "ip_address": "10.0.1.20", "role": None},
            observed_at=MOMENT,
        ),
    )


def test_json_malformed_fixture_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        json_adapter.parse(_load("malformed.json"))


def test_json_invalid_syntax_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        json_adapter.parse("{not valid json")


# --- RVTools -------------------------------------------------------------


def test_rvtools_golden_fixture_parses_exactly() -> None:
    result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)

    assert result.source_format == "rvtools"
    assert result.parser_version == rvtools_adapter.PARSER_VERSION
    assert result.record_count == 2
    assert result.observations == (
        RawObservation(
            source_format="rvtools",
            parser_version=rvtools_adapter.PARSER_VERSION,
            record_index=0,
            fields={
                "VM": "web-01",
                "Powerstate": "poweredOn",
                "CPUs": "2",
                "Memory": "4096",
                "Datacenter": "DC1",
                "Cluster": "ClusterA",
                "Host": "esxi-01.corp.local",
            },
            observed_at=MOMENT,
        ),
        RawObservation(
            source_format="rvtools",
            parser_version=rvtools_adapter.PARSER_VERSION,
            record_index=1,
            fields={
                "VM": "db-01",
                "Powerstate": "poweredOff",
                "CPUs": "4",
                "Memory": "16384",
                "Datacenter": "DC1",
                "Cluster": "ClusterA",
                "Host": "esxi-02.corp.local",
            },
            observed_at=MOMENT,
        ),
    )


def test_rvtools_malformed_fixture_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        rvtools_adapter.parse(_load("malformed.rvtools.csv"))


def test_rvtools_rejects_generic_csv() -> None:
    with pytest.raises(ValidationError):
        rvtools_adapter.parse(_load("golden.csv"))


# --- HVTools -------------------------------------------------------------


def test_hvtools_golden_fixture_parses_exactly() -> None:
    result = hvtools_adapter.parse(_load("golden.hvtools.csv"), observed_at=MOMENT)

    assert result.source_format == "hvtools"
    assert result.parser_version == hvtools_adapter.PARSER_VERSION
    assert result.record_count == 2
    assert result.observations == (
        RawObservation(
            source_format="hvtools",
            parser_version=hvtools_adapter.PARSER_VERSION,
            record_index=0,
            fields={
                "VMName": "app-01",
                "State": "Running",
                "Generation": "2",
                "CPUCount": "2",
                "MemoryAssigned": "4294967296",
                "Host": "hv-01.corp.local",
            },
            observed_at=MOMENT,
        ),
        RawObservation(
            source_format="hvtools",
            parser_version=hvtools_adapter.PARSER_VERSION,
            record_index=1,
            fields={
                "VMName": "app-02",
                "State": "Off",
                "Generation": "1",
                "CPUCount": "1",
                "MemoryAssigned": "2147483648",
                "Host": "hv-02.corp.local",
            },
            observed_at=MOMENT,
        ),
    )


def test_hvtools_malformed_fixture_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        hvtools_adapter.parse(_load("malformed.hvtools.csv"))


# --- BOM -------------------------------------------------------------------


def test_bom_golden_fixture_parses_exactly() -> None:
    result = bom_adapter.parse(_load("golden.bom.json"), observed_at=MOMENT)

    assert result.source_format == "bom"
    assert result.parser_version == bom_adapter.PARSER_VERSION
    assert result.record_count == 2
    assert result.observations == (
        RawObservation(
            source_format="bom",
            parser_version=bom_adapter.PARSER_VERSION,
            record_index=0,
            fields={
                "type": "library",
                "name": "requests",
                "version": "2.31.0",
                "licenses[0].license.id": "Apache-2.0",
            },
            observed_at=MOMENT,
        ),
        RawObservation(
            source_format="bom",
            parser_version=bom_adapter.PARSER_VERSION,
            record_index=1,
            fields={
                "type": "library",
                "name": "pyyaml",
                "version": "6.0.3",
                "licenses[0].license.id": "MIT",
            },
            observed_at=MOMENT,
        ),
    )


def test_bom_malformed_fixture_raises_clean_error() -> None:
    with pytest.raises(ValidationError):
        bom_adapter.parse(_load("malformed.bom.json"))


def test_bom_rejects_non_cyclonedx_document() -> None:
    with pytest.raises(ValidationError):
        bom_adapter.parse('{"bomFormat": "SPDX", "components": []}')


# --- cross-format -----------------------------------------------------------


def test_parser_versions_are_distinct_per_format() -> None:
    versions = {
        csv_adapter.PARSER_VERSION,
        json_adapter.PARSER_VERSION,
        rvtools_adapter.PARSER_VERSION,
        hvtools_adapter.PARSER_VERSION,
        bom_adapter.PARSER_VERSION,
    }
    assert len(versions) == 5


def test_raw_observation_fields_are_immutable() -> None:
    result = csv_adapter.parse(_load("golden.csv"))
    observation = result.observations[0]
    with pytest.raises(TypeError):
        observation.fields["hostname"] = "changed"  # type: ignore[index]
