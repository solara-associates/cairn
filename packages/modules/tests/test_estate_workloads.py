"""Tests for R1-07 workload derivation and dependency capture.

Covers the three acceptance criteria:

- workloads link resources, grouped by a shared grouping fact the
  canonical model already carries (never a fabricated heuristic);
- dependency edges between workloads are queryable (dependents and
  dependencies, from each side);
- a workload built from a resource with no grouping fact observed
  carries that through as UNVERIFIED, not a false grouping claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cairn_contracts.estate.model import FactStatus
from cairn_modules.estate import (
    UNVERIFIED,
    dependencies_of,
    dependents_of,
    derive,
    derive_dependencies,
    derive_workloads,
    normalize,
)
from cairn_modules.ingestion import csv_adapter, rvtools_adapter
from cairn_modules.ingestion.models import IngestionResult, RawObservation

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ingestion"
MOMENT = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)

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


def _derive(resources):
    return derive(resources, tenant_id=TENANT_ID, project_id=PROJECT_ID)


# --- workloads link resources ------------------------------------------------


def test_resources_sharing_a_cluster_group_into_one_workload() -> None:
    """web-01 and db-01 (golden.rvtools.csv) share Cluster=ClusterA."""
    result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    workloads, _ = _derive(resources)

    assert len(workloads) == 1
    workload = workloads[0]
    assert set(workload.resource_ids) == {r.resource_id for r in resources}
    assert workload.facts["cluster"].value == "ClusterA"
    assert workload.model_version
    assert workload.mapping_version


def test_resources_with_no_shared_grouping_fact_become_singleton_workloads() -> None:
    """app-01 and app-02 (golden.hvtools.csv) run on different hosts and
    have no cluster/datacenter fact at all -- each is its own workload.
    """
    from cairn_modules.ingestion import hvtools_adapter

    result = hvtools_adapter.parse(_load("golden.hvtools.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    workloads, _ = _derive(resources)

    assert len(workloads) == 2
    resource_ids_per_workload = {w.resource_ids for w in workloads}
    assert resource_ids_per_workload == {(r.resource_id,) for r in resources}


def test_workload_derivation_is_deterministic() -> None:
    result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    first, _ = _derive(resources)
    second, _ = _derive(resources)
    assert {w.workload_id for w in first} == {w.workload_id for w in second}


# --- dependency edges are queryable ------------------------------------------


def _resource_with_host_fact(native_id: str, host: str | None) -> IngestionResult:
    """A csv-sourced resource (identity by hostname) carrying a
    ``hypervisor_host`` fact -- not something the csv mapping emits, so
    this builds the fact directly on the normalized output instead.
    """
    return IngestionResult(
        source_format="csv",
        parser_version=csv_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": native_id, "ip_address": "10.0.0.1", "role": host},
                observed_at=MOMENT,
            ),
        ),
    )


def test_dependency_edge_resolves_when_referenced_host_was_itself_ingested() -> None:
    """A VM's hypervisor_host fact names a hostname that was also ingested
    as its own resource (as a host, via rvtools) -- a real, resolvable
    cross-resource reference becomes a dependency edge.
    """
    vm_result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)
    # The two VMs' hosts (esxi-01/02.corp.local) ingested as their own
    # resources via a plain hostname source, so the reference resolves.
    host_result = IngestionResult(
        source_format="csv",
        parser_version=csv_adapter.PARSER_VERSION,
        observations=(
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=0,
                fields={"hostname": "esxi-01.corp.local", "ip_address": "10.0.0.1", "role": "host"},
                observed_at=MOMENT,
            ),
            RawObservation(
                source_format="csv",
                parser_version=csv_adapter.PARSER_VERSION,
                record_index=1,
                fields={"hostname": "esxi-02.corp.local", "ip_address": "10.0.0.2", "role": "host"},
                observed_at=MOMENT,
            ),
        ),
    )

    resources = _normalize(vm_result, host_result)
    workloads, dependencies = _derive(resources)

    assert len(dependencies) >= 1
    by_native_id = {r.native_id: r for r in resources}
    web_workload_id = next(
        w.workload_id for w in workloads if by_native_id["web-01"].resource_id in w.resource_ids
    )
    host_workload_id = next(
        w.workload_id for w in workloads if by_native_id["esxi-01.corp.local"].resource_id in w.resource_ids
    )

    outgoing = dependencies_of(web_workload_id, dependencies)
    assert any(d.target_workload_id == host_workload_id for d in outgoing)

    incoming = dependents_of(host_workload_id, dependencies)
    assert any(d.source_workload_id == web_workload_id for d in incoming)

    # dependency_ids on the workloads themselves are populated from both sides.
    web_workload = next(w for w in workloads if w.workload_id == web_workload_id)
    host_workload = next(w for w in workloads if w.workload_id == host_workload_id)
    assert set(web_workload.dependency_ids) & set(host_workload.dependency_ids)


def test_unresolvable_host_reference_produces_no_dependency_edge() -> None:
    """The host named by hypervisor_host was never ingested -- no edge is
    fabricated from a reference that cannot be resolved.
    """
    vm_result = rvtools_adapter.parse(_load("golden.rvtools.csv"), observed_at=MOMENT)
    resources = _normalize(vm_result)
    workloads = derive_workloads(resources, tenant_id=TENANT_ID, project_id=PROJECT_ID)
    dependencies = derive_dependencies(resources, workloads)
    assert dependencies == ()


# --- UNVERIFIED propagation ---------------------------------------------------


def test_singleton_workload_carries_unverified_grouping_fact_not_a_false_claim() -> None:
    """A csv-only resource has no cluster/hypervisor_host/datacenter fact
    observed at all -- its singleton workload must not claim a grouping
    certainty the data never supported, and its environment is the same
    UNVERIFIED sentinel the canonical model uses elsewhere for unknown
    plain-string fields.
    """
    result = csv_adapter.parse(_load("golden.csv"), observed_at=MOMENT)
    resources = _normalize(result)
    workloads, dependencies = _derive(resources)

    assert len(workloads) == len(resources)
    assert dependencies == ()
    for workload in workloads:
        assert workload.environment == UNVERIFIED
        assert workload.disposition is None
        assert workload.disposition_confidence is None
        # No grouping fact was observed for a csv-only resource, so none
        # is recorded as if it had been.
        for fact in workload.facts.values():
            assert fact.status is FactStatus.UNVERIFIED
