"""R1-07: workload derivation and dependency capture.

Derives ``Workload`` entities from R1-06's canonical ``Resource``\\ s by
grouping on a shared infrastructure fact a current source mapping already
emits for that purpose (``cluster``, then ``hypervisor_host``, then
``datacenter`` -- rvtools'/hvtools' own grouping columns). No grouping
signal beyond what a mapping emits is invented: a resource with none of
these facts observed is never merged with another by coincidence of
missing data -- it becomes its own singleton workload instead.

Dependency capture reads the one canonical fact that is itself a
cross-resource reference: a VM's ``hypervisor_host`` fact names the
hostname of the host it runs on. When that host was itself ingested as
its own resource, the reference resolves to a real edge between the two
resources' workloads; when it can't be resolved (the host was never
ingested, or the reference itself is UNVERIFIED), no edge is fabricated.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from cairn_contracts.estate.model import (
    Dependency,
    DependencyDirection,
    DependencyKind,
    FactStatus,
    Resource,
    Workload,
)

from cairn_modules.estate.normalize import UNVERIFIED

#: Facts that identify the larger group a resource belongs to, in
#: preference order -- exactly the grouping columns rvtools/hvtools emit.
GROUPING_FIELDS: tuple[str, ...] = ("cluster", "hypervisor_host", "datacenter")

#: The only canonical fact whose value is itself another resource's
#: identity.
DEPENDENCY_REFERENCE_FIELD = "hypervisor_host"

#: Version tag for this deterministic, rule-based derivation. Not an
#: inferred mapping (no `INFERRED` facts are produced), but the model's
#: plain ``model_version``/``mapping_version`` fields are still required,
#: so this names the ruleset rather than leaving them UNVERIFIED -- the
#: ruleset itself is known, unlike the data it reads.
DERIVATION_VERSION = "r1-07-grouping-v1"

_WORKLOAD_NAMESPACE = uuid.UUID("7c6a1b0e-2f2b-4a7a-9b1a-6a1f0b2c3d4e")
_DEPENDENCY_NAMESPACE = uuid.UUID("9e2d4c6a-8b1f-4a3e-9c5d-1a2b3c4d5e6f")


def _workload_id(tenant_id: str, project_id: str, group_key: str) -> str:
    return str(uuid.uuid5(_WORKLOAD_NAMESPACE, f"{tenant_id}:{project_id}:{group_key}"))


def _dependency_id(source_workload_id: str, target_workload_id: str, field: str) -> str:
    return str(uuid.uuid5(_DEPENDENCY_NAMESPACE, f"{source_workload_id}:{target_workload_id}:{field}"))


def _grouping_signal(resource: Resource) -> tuple[str, str] | None:
    """The first grouping fact this resource actually observed, if any."""
    for field in GROUPING_FIELDS:
        fact = resource.facts.get(field)
        if fact is not None and fact.status is not FactStatus.UNVERIFIED and fact.value:
            return field, str(fact.value)
    return None


def derive_workloads(
    resources: Sequence[Resource],
    *,
    tenant_id: str,
    project_id: str,
) -> tuple[Workload, ...]:
    """Group ``resources`` into ``Workload``\\ s by shared grouping signal.

    Resources sharing the same (grouping field, value) become one
    workload. A resource with none of the grouping facts observed
    becomes its own singleton workload, carrying those facts through as
    the UNVERIFIED values they are -- never defaulted into a grouping
    decision the data doesn't support.
    """
    groups: dict[tuple[str, str], list[Resource]] = defaultdict(list)
    singles: list[Resource] = []

    for resource in resources:
        signal = _grouping_signal(resource)
        if signal is None:
            singles.append(resource)
        else:
            groups[signal].append(resource)

    workloads: list[Workload] = []

    for (field, value), members in sorted(groups.items()):
        resource_ids = tuple(sorted(r.resource_id for r in members))
        grouping_fact = next(r.facts[field] for r in members if field in r.facts)
        workloads.append(
            Workload(
                workload_id=_workload_id(tenant_id, project_id, f"{field}:{value}"),
                tenant_id=tenant_id,
                project_id=project_id,
                name=f"{field}:{value}",
                environment=UNVERIFIED,
                owner=None,
                business_context=None,
                resource_ids=resource_ids,
                dependency_ids=(),
                facts={field: grouping_fact},
                disposition=None,
                disposition_confidence=None,
                model_version=DERIVATION_VERSION,
                mapping_version=DERIVATION_VERSION,
            )
        )

    for resource in sorted(singles, key=lambda r: r.resource_id):
        facts = {field: resource.facts[field] for field in GROUPING_FIELDS if field in resource.facts}
        workloads.append(
            Workload(
                workload_id=_workload_id(tenant_id, project_id, f"resource:{resource.resource_id}"),
                tenant_id=tenant_id,
                project_id=project_id,
                name=resource.name or resource.native_id,
                environment=UNVERIFIED,
                owner=None,
                business_context=None,
                resource_ids=(resource.resource_id,),
                dependency_ids=(),
                facts=facts,
                disposition=None,
                disposition_confidence=None,
                model_version=DERIVATION_VERSION,
                mapping_version=DERIVATION_VERSION,
            )
        )

    return tuple(workloads)


def derive_dependencies(
    resources: Sequence[Resource],
    workloads: Sequence[Workload],
) -> tuple[Dependency, ...]:
    """Capture dependency edges from the one cross-resource reference the
    canonical model carries: a VM's ``hypervisor_host`` fact naming the
    hostname of a separately-ingested host resource.

    An edge is only created when the referenced host was itself ingested
    as its own resource (identity match by hostname) and the reference
    fact was actually observed. A reference that can't be resolved, or
    that is itself UNVERIFIED, produces no edge.
    """
    by_native_id: dict[str, Resource] = {r.native_id: r for r in resources}
    workload_of_resource: dict[str, str] = {
        resource_id: workload.workload_id for workload in workloads for resource_id in workload.resource_ids
    }

    dependencies: list[Dependency] = []
    seen_pairs: set[tuple[str, str]] = set()

    for resource in sorted(resources, key=lambda r: r.resource_id):
        fact = resource.facts.get(DEPENDENCY_REFERENCE_FIELD)
        if fact is None or fact.status is FactStatus.UNVERIFIED or not fact.value:
            continue

        host = by_native_id.get(str(fact.value))
        if host is None or host.resource_id == resource.resource_id:
            continue

        source_workload_id = workload_of_resource.get(resource.resource_id)
        target_workload_id = workload_of_resource.get(host.resource_id)
        if source_workload_id is None or target_workload_id is None:
            continue
        if source_workload_id == target_workload_id:
            continue

        pair = (source_workload_id, target_workload_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        provenance = tuple(p for p in resource.provenance if p.raw_ref == fact.provenance_ref)
        if not provenance:
            provenance = resource.provenance

        dependencies.append(
            Dependency(
                dependency_id=_dependency_id(
                    source_workload_id, target_workload_id, DEPENDENCY_REFERENCE_FIELD
                ),
                tenant_id=resource.tenant_id,
                project_id=resource.project_id,
                source_workload_id=source_workload_id,
                target_workload_id=target_workload_id,
                kind=DependencyKind.OTHER,
                direction=DependencyDirection.ONE_WAY,
                status=FactStatus.OBSERVED,
                provenance=provenance,
            )
        )

    return tuple(dependencies)


def attach_dependency_ids(
    workloads: Sequence[Workload],
    dependencies: Sequence[Dependency],
) -> tuple[Workload, ...]:
    """Return ``workloads`` with ``dependency_ids`` set from ``dependencies``."""
    by_workload: dict[str, set[str]] = defaultdict(set)
    for dependency in dependencies:
        by_workload[dependency.source_workload_id].add(dependency.dependency_id)
        by_workload[dependency.target_workload_id].add(dependency.dependency_id)

    return tuple(
        workload.model_copy(
            update={"dependency_ids": tuple(sorted(by_workload.get(workload.workload_id, ())))}
        )
        for workload in workloads
    )


def derive(
    resources: Sequence[Resource],
    *,
    tenant_id: str,
    project_id: str,
) -> tuple[tuple[Workload, ...], tuple[Dependency, ...]]:
    """Derive workloads and their dependency edges from ``resources`` in one pass."""
    workloads = derive_workloads(resources, tenant_id=tenant_id, project_id=project_id)
    dependencies = derive_dependencies(resources, workloads)
    workloads = attach_dependency_ids(workloads, dependencies)
    return workloads, dependencies


def dependencies_of(workload_id: str, dependencies: Sequence[Dependency]) -> tuple[Dependency, ...]:
    """Edges where ``workload_id`` is the source -- what it depends on."""
    return tuple(d for d in dependencies if d.source_workload_id == workload_id)


def dependents_of(workload_id: str, dependencies: Sequence[Dependency]) -> tuple[Dependency, ...]:
    """Edges where ``workload_id`` is the target -- what depends on it."""
    return tuple(d for d in dependencies if d.target_workload_id == workload_id)


__all__ = [
    "DEPENDENCY_REFERENCE_FIELD",
    "DERIVATION_VERSION",
    "GROUPING_FIELDS",
    "attach_dependency_ids",
    "dependencies_of",
    "dependents_of",
    "derive",
    "derive_dependencies",
    "derive_workloads",
]
