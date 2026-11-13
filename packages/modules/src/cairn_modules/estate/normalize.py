"""R1-06: canonical estate normalization and provenance.

Maps raw observations from R1-03's ingestion adapters (``RawObservation`` /
``IngestionResult``, the common shape every file adapter produces) into
``contracts/estate``'s canonical ``Resource`` entities.

Rules enforced here (ADR-003, implementation spec §6.2-6.3):

- Every fact carries provenance: which source observed it, when, and which
  parser version produced the observation.
- Observations of the same real-world thing from *different* sources are
  attributed to one ``Resource`` (matched by the source's own identity
  field -- hostname, VM name, component name, ...); they are never silently
  collapsed into a single source's view.
- When two sources disagree on the value of the same canonical field, both
  values are preserved as separate, individually retrievable facts rather
  than one overwriting the other. ``conflicts()`` below finds them.
- A canonical field that no contributing source observed is explicit
  ``FactValue(status=UNVERIFIED)`` -- never a default, never a guess.

This module intentionally depends only on R1-03's common raw shape
(``cairn_modules.ingestion.models``), not on any specific provider adapter
(e.g. the GCP inventory adapter, R1-05), so it is not blocked on R1-05.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from cairn_contracts.estate.model import FactStatus, FactValue, Provenance, Resource

from cairn_modules.estate.errors import MissingIdentityError, UnsupportedSourceFormatError
from cairn_modules.estate.mapping import source_mapping
from cairn_modules.ingestion.models import IngestionResult, RawObservation

#: Sentinel for a structural identity field (``Resource.provider`` etc.) that
#: no file-ingestion source can ever populate. These are plain ``str``
#: fields on ``Resource`` (not ``FactValue``), so they cannot hold a
#: ``FactStatus`` -- this is the "missing = UNVERIFIED" rule applied to
#: that part of the model.
UNVERIFIED = "UNVERIFIED"

#: Conflicting facts for the same canonical field are stored under separate
#: keys, ``f"{field}{CONFLICT_SEPARATOR}{source_format}"``, rather than one
#: key whose value silently wins. ``conflicts()`` groups them back up.
CONFLICT_SEPARATOR = "@"

_RESOURCE_NAMESPACE = uuid.UUID("5e3b8b0a-9b63-4c7e-9a9a-5b7a9a7f0c1a")


def _resource_id(tenant_id: str, project_id: str, native_id: str) -> str:
    return str(uuid.uuid5(_RESOURCE_NAMESPACE, f"{tenant_id}:{project_id}:{native_id}"))


class _Contribution:
    __slots__ = ("observation", "record_index", "source_format")

    def __init__(self, observation: RawObservation, source_format: str, record_index: int) -> None:
        self.observation = observation
        self.source_format = source_format
        self.record_index = record_index


def _unverified_fact() -> FactValue:
    return FactValue(
        value=None,
        status=FactStatus.UNVERIFIED,
        source="",
        observed_at=None,
        ingested_at=datetime.now(UTC),
        confidence=None,
        mapping_version=None,
        provenance_ref="",
    )


def _build_facts(contributions: Sequence[_Contribution]) -> dict[str, FactValue]:
    """Build the canonical ``facts`` dict for one resolved resource identity.

    ``contributions`` is every raw observation (from any source format)
    that resolved to this same resource.
    """
    now = datetime.now(UTC)

    # Which canonical fields are even meaningful for this resource, and
    # which raw field each contributing format uses for it.
    canonical_fields: dict[str, dict[str, str]] = defaultdict(dict)
    for contribution in contributions:
        mapping = source_mapping(contribution.source_format)
        for canonical_name, raw_field in mapping.fact_fields.items():
            canonical_fields[canonical_name][contribution.source_format] = raw_field

    facts: dict[str, FactValue] = {}
    for canonical_name, raw_field_by_format in canonical_fields.items():
        # Every value a contributing source actually reported for this field.
        observed: list[tuple[str, str, datetime, str]] = []  # (source, value, observed_at, raw_ref)
        for contribution in contributions:
            raw_field = raw_field_by_format.get(contribution.source_format)
            if raw_field is None:
                continue  # this source format does not carry this field at all
            value = contribution.observation.fields.get(raw_field)
            if value is None:
                continue  # this source looked and found nothing -- not a conflict signal
            raw_ref = f"{contribution.source_format}#{contribution.record_index}"
            observed.append((contribution.source_format, value, contribution.observation.observed_at, raw_ref))

        if not observed:
            facts[canonical_name] = _unverified_fact()
            continue

        distinct_values = {value for _, value, _, _ in observed}
        if len(distinct_values) == 1:
            sources = sorted({source for source, _, _, _ in observed})
            _, value, _, _ = observed[0]
            latest_observed_at = max(observed_at for _, _, observed_at, _ in observed)
            raw_ref = observed[0][3]
            facts[canonical_name] = FactValue(
                value=value,
                status=FactStatus.OBSERVED,
                source=",".join(sources),
                observed_at=latest_observed_at,
                ingested_at=now,
                confidence=None,
                mapping_version=None,
                provenance_ref=raw_ref,
            )
        else:
            # Conflicting observations: preserve each one, individually
            # retrievable, instead of picking a winner.
            for source, value, observed_at, raw_ref in observed:
                key = f"{canonical_name}{CONFLICT_SEPARATOR}{source}"
                facts[key] = FactValue(
                    value=value,
                    status=FactStatus.OBSERVED,
                    source=source,
                    observed_at=observed_at,
                    ingested_at=now,
                    confidence=None,
                    mapping_version=None,
                    provenance_ref=raw_ref,
                )

    return facts


def _provenance(contribution: _Contribution, ingest_run_id: str) -> Provenance:
    return Provenance(
        source_system=contribution.source_format,
        source_id=f"{contribution.source_format}:{contribution.record_index}",
        source_version=None,
        observed_at=contribution.observation.observed_at,
        ingested_at=datetime.now(UTC),
        parser_version=contribution.observation.parser_version,
        ingest_run_id=ingest_run_id,
        raw_ref=f"{contribution.source_format}#{contribution.record_index}",
    )


def _resource_type(contributions: Sequence[_Contribution]) -> str:
    types = {source_mapping(c.source_format).resource_type for c in contributions}
    if len(types) == 1:
        return next(iter(types))
    return "mixed"


def normalize(
    results: Iterable[IngestionResult],
    *,
    tenant_id: str,
    project_id: str,
    ingest_run_id: str,
) -> tuple[Resource, ...]:
    """Normalize one or more ``IngestionResult``\\ s into canonical ``Resource``\\ s.

    Observations across every result are matched by identity (the source
    format's own identity field) before resources are built, so the same
    real-world resource observed by two different source files becomes one
    ``Resource`` with provenance and facts from both.

    Raises ``UnsupportedSourceFormatError`` for a source format this module
    has no mapping for, and ``MissingIdentityError`` for an observation
    whose identity field is missing or empty -- both fail closed rather
    than fabricating a resource.
    """
    groups: dict[str, list[_Contribution]] = defaultdict(list)

    for result in results:
        try:
            mapping = source_mapping(result.source_format)
        except KeyError as exc:
            raise UnsupportedSourceFormatError(
                f"no canonical mapping for source format '{result.source_format}'"
            ) from exc

        for observation in result.observations:
            identity = observation.fields.get(mapping.identity_field)
            if not identity:
                raise MissingIdentityError(
                    f"{result.source_format} record {observation.record_index} has no "
                    f"value for identity field '{mapping.identity_field}'"
                )
            groups[identity].append(
                _Contribution(
                    observation=observation,
                    source_format=result.source_format,
                    record_index=observation.record_index,
                )
            )

    resources: list[Resource] = []
    for identity, contributions in groups.items():
        resources.append(
            Resource(
                resource_id=_resource_id(tenant_id, project_id, identity),
                tenant_id=tenant_id,
                project_id=project_id,
                provider=UNVERIFIED,
                account_id=UNVERIFIED,
                region=UNVERIFIED,
                service="/".join(sorted({c.source_format for c in contributions})),
                resource_type=_resource_type(contributions),
                native_id=identity,
                name=identity,
                tags={},
                facts=_build_facts(contributions),
                provenance=tuple(_provenance(c, ingest_run_id) for c in contributions),
                status=FactStatus.OBSERVED,
            )
        )

    return tuple(resources)


def conflicts(resource: Resource) -> dict[str, tuple[FactValue, ...]]:
    """Return every canonical field on ``resource`` with conflicting values.

    The result maps each canonical field name to the tuple of conflicting
    ``FactValue``\\ s (one per disagreeing source), so a conflict recorded
    by :func:`normalize` stays queryable rather than requiring callers to
    know the internal key convention.
    """
    grouped: dict[str, list[FactValue]] = defaultdict(list)
    for key, fact in resource.facts.items():
        if CONFLICT_SEPARATOR in key:
            field, _, _source = key.partition(CONFLICT_SEPARATOR)
            grouped[field].append(fact)
    return {field: tuple(values) for field, values in grouped.items()}


__all__ = [
    "CONFLICT_SEPARATOR",
    "UNVERIFIED",
    "conflicts",
    "normalize",
]
