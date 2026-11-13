"""Tests for R1-06 canonical estate normalization and provenance.

Covers the three acceptance criteria:

- conflicting observations from different sources are preserved and
  queryable, not collapsed to one value;
- a canonical field with no observing source is explicit ``UNVERIFIED``,
  never a default or a guess;
- normalizing R1-03's own golden ingestion fixtures end-to-end produces
  resources with correct identity, facts and provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cairn_contracts.estate.model import FactStatus
from cairn_modules.estate import (
    UNVERIFIED,
    MissingIdentityError,
    UnsupportedSourceFormatError,
    conflicts,
    normalize,
)
from cairn_modules.ingestion import (
    bom_adapter,
    csv_adapter,
    hvtools_adapter,
    json_adapter,
    rvtools_adapter,
)
from cairn_modules.ingestion.models import IngestionResult, RawObservation

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ingestion"
MOMENT = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 13, 13, 0, 0, tzinfo=UTC)

TENANT_ID = "tenant-1"
PROJECT_ID = "project-1"
INGEST_RUN_ID = "run-1"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _normalize(*results: IngestionResult):
    return normalize(
        results,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        ingest_run_id=INGEST_RUN_ID,
    )


# --- conflicting observations preserved and queryable -----------------------


def test_conflicting_observation_across_sources_is_preserved_not_overwritten() -> None:
    """Two sources disagreeing on the same field keep both values."""
    first = IngestionResult(
        source_format="rvtools",
        parser_version="rvtools-adapter-1.0.0",
        observations=(
            RawObservation(
                source_format="rvtools",
                parser_version="rvtools-adapter-1.0.0",
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
        ),
    )
    # A second, later rescan reports a different CPU count for the same VM.
    second = IngestionResult(
        source_format="hvtools",
        parser_version="hvtools-adapter-1.0.0",
        observations=(
            RawObservation(
                source_format="hvtools",
                parser_version="hvtools-adapter-1.0.0",
                record_index=0,
                fields={
                    "VMName": "web-01",
                    "State": "Running",
                    "Generation": "2",
                    "CPUCount": "4",
                    "MemoryAssigned": "4294967296",
                    "Host": "hv-01.corp.local",
                },
                observed_at=LATER,
            ),
        ),
    )

    resources = _normalize(first, second)
    assert len(resources) == 1
    resource = resources[0]

    # Both conflicting cpu_count observations survive, individually.
    assert "cpu_count@rvtools" in resource.facts
    assert "cpu_count@hvtools" in resource.facts
    assert resource.facts["cpu_count@rvtools"].value == "2"
    assert resource.facts["cpu_count@hvtools"].value == "4"
    assert resource.facts["cpu_count@rvtools"].status is FactStatus.OBSERVED
    assert resource.facts["cpu_count@hvtools"].status is FactStatus.OBSERVED
    # No single "cpu_count" key picks a winner.
    assert "cpu_count" not in resource.facts

    # The conflict is queryable without knowing the key convention.
    found = conflicts(resource)
    assert set(found["cpu_count"]) == {
        resource.facts["cpu_count@rvtools"],
        resource.facts["cpu_count@hvtools"],
    }

    # Provenance from both contributing sources is retained.
    source_systems = {p.source_system for p in resource.provenance}
    assert source_systems == {"rvtools", "hvtools"}

    # power_state and hypervisor_host also conflict between the two scans;
    # every disagreeing field is reported, not just the first one found.
    assert set(found) == {"cpu_count", "power_state", "hypervisor_host"}


def test_agreeing_observations_merge_into_one_fact_with_both_sources() -> None:
    first = IngestionResult(
        source_format="csv",
        parser_version=csv_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": "web-01", "ip_address": "10.0.1.10", "role": "web"},
                observed_at=MOMENT,
            ),
        ),
    )
    second = IngestionResult(
        source_format="json",
        parser_version=json_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="json",
                parser_version=json_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": "web-01", "ip_address": "10.0.1.10", "role": "web"},
                observed_at=LATER,
            ),
        ),
    )

    resources = _normalize(first, second)
    assert len(resources) == 1
    resource = resources[0]

    assert resource.facts["role"].value == "web"
    assert resource.facts["role"].status is FactStatus.OBSERVED
    assert resource.facts["role"].source == "csv,json"
    assert not conflicts(resource)


# --- missing field is explicit UNVERIFIED -----------------------------------


def test_field_with_no_observing_source_is_unverified() -> None:
    result = IngestionResult(
        source_format="csv",
        parser_version=csv_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": "db-01", "ip_address": "10.0.1.20", "role": None},
                observed_at=MOMENT,
            ),
        ),
    )

    resources = _normalize(result)
    assert len(resources) == 1
    resource = resources[0]

    assert resource.facts["role"].value is None
    assert resource.facts["role"].status is FactStatus.UNVERIFIED
    assert resource.facts["ip_address"].value == "10.0.1.20"


def test_structural_identity_fields_are_unverified_sentinel_for_file_sources() -> None:
    """File ingestion carries no provider/account/region -- never fabricated."""
    result = csv_adapter.parse(_load("golden.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    for resource in resources:
        assert resource.provider == UNVERIFIED
        assert resource.account_id == UNVERIFIED
        assert resource.region == UNVERIFIED


def test_missing_identity_field_fails_closed() -> None:
    result = IngestionResult(
        source_format="csv",
        parser_version=csv_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": None, "ip_address": "10.0.1.10", "role": "web"},
                observed_at=MOMENT,
            ),
        ),
    )
    with pytest.raises(MissingIdentityError):
        _normalize(result)


def test_unsupported_source_format_fails_closed() -> None:
    result = IngestionResult(
        source_format="not-a-real-format",
        parser_version="x-1.0.0",
        observations=(
            RawObservation(
                source_format="not-a-real-format",
                parser_version="x-1.0.0",
                record_index=0,
                fields={"id": "1"},
                observed_at=MOMENT,
            ),
        ),
    )
    with pytest.raises(UnsupportedSourceFormatError):
        _normalize(result)


# --- golden fixture end-to-end -----------------------------------------------


def test_golden_csv_and_rvtools_fixtures_merge_by_hostname_end_to_end() -> None:
    """R1-03's own csv and rvtools golden fixtures describe the same two
    hosts (web-01, db-01); normalizing both together must attribute each
    host's facts to a single resource with provenance from both sources.
    """
    csv_result = csv_adapter.parse(_load("golden.csv"), observed_at=MOMENT)
    rvtools_result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)

    resources = _normalize(csv_result, rvtools_result)
    by_name = {r.native_id: r for r in resources}

    assert set(by_name) == {"web-01", "db-01"}

    web = by_name["web-01"]
    assert web.facts["role"].value == "web"
    assert web.facts["power_state"].value == "poweredOn"
    assert web.facts["cpu_count"].value == "2"
    assert {p.source_system for p in web.provenance} == {"csv", "rvtools"}
    assert web.resource_type == "mixed"
    assert web.service == "csv/rvtools"

    db = by_name["db-01"]
    assert db.facts["role"].status is FactStatus.UNVERIFIED  # csv row has an empty role
    assert db.facts["power_state"].value == "poweredOff"


def test_golden_hvtools_fixture_normalizes_end_to_end() -> None:
    result = hvtools_adapter.parse(_load("golden.hvtools.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    by_name = {r.native_id: r for r in resources}

    assert set(by_name) == {"app-01", "app-02"}
    assert by_name["app-01"].facts["cpu_count"].value == "2"
    assert by_name["app-01"].resource_type == "virtual-machine"
    assert by_name["app-02"].facts["power_state"].value == "Off"


def test_golden_json_fixture_normalizes_end_to_end() -> None:
    result = json_adapter.parse(_load("golden.json"), observed_at=MOMENT)
    resources = _normalize(result)
    by_name = {r.native_id: r for r in resources}

    assert set(by_name) == {"web-01", "db-01"}
    assert by_name["web-01"].facts["role"].value == "web"
    assert by_name["db-01"].facts["role"].status is FactStatus.UNVERIFIED


def test_golden_bom_fixture_normalizes_end_to_end() -> None:
    result = bom_adapter.parse(_load("golden.bom.json"), observed_at=MOMENT)
    resources = _normalize(result)
    by_name = {r.native_id: r for r in resources}

    assert set(by_name) == {"requests", "pyyaml"}
    requests = by_name["requests"]
    assert requests.resource_type == "software-component"
    assert requests.facts["component_version"].value == "2.31.0"
    assert requests.facts["license"].value == "Apache-2.0"


def test_resource_id_is_deterministic_for_the_same_identity() -> None:
    result = csv_adapter.parse(_load("golden.csv"), observed_at=MOMENT)
    first = _normalize(result)
    second = _normalize(result)
    assert {r.resource_id for r in first} == {r.resource_id for r in second}
