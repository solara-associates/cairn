"""R2-01: the resolver -- spec 9.3's "Resolve mapping" contract, and ADR-004's
"the resolver is the only way modules obtain a mapping."

A pure function: given an already-published ``MappingRelease`` and a
source/target/region query, it returns exactly spec 9.3's response shape
or raises. It never invents a substitute for a missing or ``UNAVAILABLE``
mapping (spec 7.3) -- there is no fallback path here, only
``MappingUnavailableError``.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingEntry, MappingRelease
from cairn_kernel.errors import MappingUnavailableError


@dataclass(frozen=True, slots=True)
class ResolvedMapping:
    source_provider: str
    source_service: str
    target_provider: str
    target_service: str | None
    equivalence: Equivalence
    caveat: str | None
    region_supported: bool
    mapping_version: str
    evidence: str


def _find_entry(
    release: MappingRelease, *, source_provider: str, source_service: str, target_provider: str
) -> MappingEntry | None:
    for entry in release.entries:
        if (
            entry.source_provider == source_provider
            and entry.source_service == source_service
            and entry.target_provider == target_provider
        ):
            return entry
    return None


def resolve_mapping(
    release: MappingRelease,
    *,
    source_provider: str,
    source_service: str,
    target_provider: str,
    region: str | None = None,
) -> ResolvedMapping:
    """Resolve ``source_provider``:``source_service`` -> ``target_provider``
    against one published ``release``.

    Raises ``MappingUnavailableError`` -- with an explanation, never a
    substitute -- when no entry matches the source/target pair at all, or
    when the matching entry's ``equivalence`` is ``UNAVAILABLE``.
    """
    entry = _find_entry(
        release,
        source_provider=source_provider,
        source_service=source_service,
        target_provider=target_provider,
    )
    if entry is None:
        raise MappingUnavailableError(
            f"no mapping from {source_provider}:{source_service} to {target_provider}"
            f" in release {release.version}"
        )
    if entry.equivalence is Equivalence.UNAVAILABLE:
        raise MappingUnavailableError(
            entry.caveat
            or (
                f"{source_provider}:{source_service} has no equivalent on {target_provider}"
                f" in release {release.version}"
            )
        )
    region_supported = region is None or not entry.regions or region in entry.regions
    return ResolvedMapping(
        source_provider=entry.source_provider,
        source_service=entry.source_service,
        target_provider=entry.target_provider,
        target_service=entry.target_service,
        equivalence=entry.equivalence,
        caveat=entry.caveat,
        region_supported=region_supported,
        mapping_version=release.version,
        evidence=entry.evidence,
    )


__all__ = ["ResolvedMapping", "resolve_mapping"]
