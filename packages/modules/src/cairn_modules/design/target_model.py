"""R2-04: the target model generator (spec §16's R2-04 row: "Deterministic
from estate + pattern + parameters; records versions").

Given a project's canonical estate (``cairn_contracts.estate.Resource``,
R1-06's normalization output), one published pattern
(``cairn_contracts.mapping.pattern.Pattern``, R2-03's ``PatternRepository``)
and caller-supplied parameters, ``generate_target_model`` resolves every
source resource through R2-01's real mapping resolver
(``cairn_modules.mappings.resolver.resolve_mapping``) against one
published ``MappingRelease`` and produces a ``TargetModel``.

Determinism (no randomness, no wall-clock-dependent ordering) is the whole
point of this story: the same ``estate``/``pattern``/``mapping_release``/
``parameters`` input must produce a byte-identical ``TargetModel.
content_hash`` on every call. Resource order in the input is not assumed
to be canonical, so resolved entries are always re-sorted by
``resource_id`` before hashing.

ADR-003 ("one canonical estate model") bounds this module: it resolves
exactly what the estate already states, through exactly the mapping the
resolver returns. It never re-interprets an estate fact and never invents
a target resource for something the resolver could not resolve -- an
``UNAVAILABLE``/``UNRESOLVED`` result is carried into the output as a
first-class, visible entry (see ``TargetResourceEntry``), never silently
dropped and never replaced with a guessed substitute.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from cairn_contracts.estate import Resource
from cairn_contracts.mapping import MappingRelease
from cairn_contracts.mapping.pattern import Pattern, PatternParameterType
from cairn_kernel.errors import MappingUnavailableError, ValidationError

from cairn_modules.mappings.resolver import ResolvedMapping, resolve_mapping


class TargetResourceStatus(str, Enum):
    """Whether a source resource could be carried into the target model."""

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class TargetResourceEntry:
    """One source resource's outcome against the mapping resolver.

    ``resolution`` is set only when ``status`` is ``RESOLVED``. When
    ``status`` is ``UNRESOLVED`` -- the resolver raised
    ``MappingUnavailableError``, whether because no mapping entry exists
    at all or because the matching entry's equivalence is itself
    ``UNAVAILABLE`` -- ``resolution`` is ``None`` and ``reason`` carries
    the resolver's own explanation. Spec 7.3: "UNAVAILABLE fails
    generation with an explanation; it never invents a substitute" -- this
    is that explanation, surfaced per-resource rather than aborting the
    whole generation.
    """

    resource_id: str
    source_provider: str
    source_service: str
    status: TargetResourceStatus
    resolution: ResolvedMapping | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status is TargetResourceStatus.RESOLVED and self.resolution is None:
            raise ValueError("a RESOLVED entry must carry a resolution")
        if self.status is TargetResourceStatus.UNRESOLVED and self.resolution is not None:
            raise ValueError("an UNRESOLVED entry must not carry a resolution")
        if self.status is TargetResourceStatus.UNRESOLVED and not self.reason:
            raise ValueError("an UNRESOLVED entry must carry a reason")


@dataclass(frozen=True, slots=True)
class TargetModel:
    """The deterministic output of one target-model generation.

    Carries the exact mapping release version, pattern catalogue version
    and parameter set used to produce it (spec's repeated "records
    versions" requirement -- what R2-10 later checks for consistency),
    plus every source resource's resolution outcome, sorted by
    ``resource_id`` so that re-running generation with the same inputs
    produces byte-identical output regardless of the estate's input
    order.
    """

    tenant_id: str
    project_id: str
    design_id: str
    pattern_id: str
    pattern_catalogue_version: str
    mapping_release_version: str
    target_provider: str
    parameters: tuple[tuple[str, Any], ...]
    resources: tuple[TargetResourceEntry, ...]

    @property
    def unresolved_resource_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.resource_id
            for entry in self.resources
            if entry.status is TargetResourceStatus.UNRESOLVED
        )

    @property
    def content_hash(self) -> str:
        """A stable fingerprint of this target model's content.

        Deterministic: built from a plain-data projection of every field,
        serialized with sorted keys and no locale- or platform-dependent
        formatting. Two ``TargetModel`` instances built from the same
        inputs always hash identically.
        """
        payload = {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "design_id": self.design_id,
            "pattern_id": self.pattern_id,
            "pattern_catalogue_version": self.pattern_catalogue_version,
            "mapping_release_version": self.mapping_release_version,
            "target_provider": self.target_provider,
            "parameters": [[key, value] for key, value in self.parameters],
            "resources": [_entry_to_jsonable(entry) for entry in self.resources],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_to_jsonable(entry: TargetResourceEntry) -> dict[str, Any]:
    resolution: dict[str, Any] | None = None
    if entry.resolution is not None:
        resolution = {
            "source_provider": entry.resolution.source_provider,
            "source_service": entry.resolution.source_service,
            "target_provider": entry.resolution.target_provider,
            "target_service": entry.resolution.target_service,
            "equivalence": entry.resolution.equivalence.value,
            "caveat": entry.resolution.caveat,
            "region_supported": entry.resolution.region_supported,
            "mapping_version": entry.resolution.mapping_version,
            "evidence": entry.resolution.evidence,
        }
    return {
        "resource_id": entry.resource_id,
        "source_provider": entry.source_provider,
        "source_service": entry.source_service,
        "status": entry.status.value,
        "resolution": resolution,
        "reason": entry.reason,
    }


_PARAMETER_TYPE_CHECKS: dict[PatternParameterType, tuple[type, ...]] = {
    PatternParameterType.STRING: (str,),
    PatternParameterType.INTEGER: (int,),
    PatternParameterType.BOOLEAN: (bool,),
    PatternParameterType.ENUM: (str,),
    PatternParameterType.STRING_LIST: (list, tuple),
}


def _resolve_parameters(
    pattern: Pattern, parameters: dict[str, Any]
) -> tuple[tuple[str, Any], ...]:
    """Apply ``pattern``'s parameter schema to caller-supplied ``parameters``.

    Unknown parameter names are rejected (no silent pass-through of
    something the pattern never declared). A missing required parameter
    is rejected. A missing optional parameter is filled with its declared
    default -- so two calls that differ only in omitting a default-valued
    parameter still produce identical, deterministic output. The result
    is sorted by name so parameter order never affects
    ``TargetModel.content_hash``.
    """
    declared = {parameter.name: parameter for parameter in pattern.parameters}
    unknown = set(parameters) - set(declared)
    if unknown:
        raise ValidationError(
            f"pattern {pattern.id!r} does not declare parameter(s): {sorted(unknown)}"
        )

    resolved: dict[str, Any] = {}
    for name, parameter in declared.items():
        if name in parameters:
            value = parameters[name]
        elif not parameter.required:
            value = parameter.default
        else:
            raise ValidationError(
                f"pattern {pattern.id!r} requires parameter {name!r}"
            )

        if value is not None:
            if parameter.type is PatternParameterType.STRING_LIST:
                if not isinstance(value, list | tuple) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise ValidationError(
                        f"parameter {name!r} must be a list of strings"
                    )
                value = tuple(value)
            else:
                expected_types = _PARAMETER_TYPE_CHECKS[parameter.type]
                if not isinstance(value, expected_types) or isinstance(value, bool) != (
                    parameter.type is PatternParameterType.BOOLEAN
                ):
                    raise ValidationError(
                        f"parameter {name!r} must be of type {parameter.type.value}"
                    )
                if (
                    parameter.type is PatternParameterType.ENUM
                    and value not in parameter.allowed_values
                ):
                    raise ValidationError(
                        f"parameter {name!r} must be one of {parameter.allowed_values}"
                    )
        resolved[name] = value

    return tuple(sorted(resolved.items()))


def generate_target_model(
    *,
    tenant_id: str,
    project_id: str,
    design_id: str,
    estate: tuple[Resource, ...],
    pattern: Pattern,
    pattern_catalogue_version: str,
    mapping_release: MappingRelease,
    target_provider: str,
    parameters: dict[str, Any] | None = None,
) -> TargetModel:
    """Generate one deterministic ``TargetModel``.

    ``mapping_release`` must already be the published release this
    generation names (callers obtain it via
    ``MappingRepository.get_published(version)``); ``pattern`` must
    already be the published pattern this generation names (via
    ``PatternRepository.get_published(...)``/``get(...)``) -- this
    function does not itself resolve a version string to content, only
    content to a target model, so the exact versions it was given are
    what it records.

    Every resource in ``estate`` is resolved independently; one
    resource's ``UNRESOLVED`` outcome never aborts generation for the
    others (spec 7.3's "never invents a substitute" is about content, not
    about refusing to report the rest of the estate).
    """
    resolved_parameters = _resolve_parameters(pattern, parameters or {})

    entries: list[TargetResourceEntry] = []
    for resource in estate:
        try:
            resolution = resolve_mapping(
                mapping_release,
                source_provider=resource.provider,
                source_service=resource.service,
                target_provider=target_provider,
                region=resource.region,
            )
        except MappingUnavailableError as exc:
            entries.append(
                TargetResourceEntry(
                    resource_id=resource.resource_id,
                    source_provider=resource.provider,
                    source_service=resource.service,
                    status=TargetResourceStatus.UNRESOLVED,
                    resolution=None,
                    reason=str(exc),
                )
            )
            continue
        entries.append(
            TargetResourceEntry(
                resource_id=resource.resource_id,
                source_provider=resource.provider,
                source_service=resource.service,
                status=TargetResourceStatus.RESOLVED,
                resolution=resolution,
                reason=None,
            )
        )

    entries.sort(key=lambda entry: entry.resource_id)

    return TargetModel(
        tenant_id=tenant_id,
        project_id=project_id,
        design_id=design_id,
        pattern_id=pattern.id,
        pattern_catalogue_version=pattern_catalogue_version,
        mapping_release_version=mapping_release.version,
        target_provider=target_provider,
        parameters=resolved_parameters,
        resources=tuple(entries),
    )


__all__ = [
    "TargetModel",
    "TargetResourceEntry",
    "TargetResourceStatus",
    "generate_target_model",
]
