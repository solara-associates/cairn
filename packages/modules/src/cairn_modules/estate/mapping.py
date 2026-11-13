"""Per-source-format field mapping for canonical estate normalization.

R1-03 adapters hand back a ``RawObservation`` whose ``fields`` are the
source file's own column/key names, verbatim. This module is the only place
that knows which raw field identifies a record (so observations from
different files can be recognized as the same resource) and which raw
fields correspond to which canonical fact names.

Adding support for a new ingestion source format means adding one entry
here -- nothing else in :mod:`cairn_modules.estate` should need to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class SourceMapping:
    """How one ingestion source format maps onto the canonical model."""

    #: Raw field name that identifies the record (becomes ``Resource.native_id``).
    identity_field: str
    #: canonical fact name -> raw field name.
    fact_fields: MappingProxyType[str, str]
    #: ``Resource.resource_type`` for a resource built only from this format.
    resource_type: str


_SOURCE_MAPPINGS: dict[str, SourceMapping] = {
    "csv": SourceMapping(
        identity_field="hostname",
        fact_fields=MappingProxyType({"ip_address": "ip_address", "role": "role"}),
        resource_type="unknown",
    ),
    "json": SourceMapping(
        identity_field="hostname",
        fact_fields=MappingProxyType({"ip_address": "ip_address", "role": "role"}),
        resource_type="unknown",
    ),
    "rvtools": SourceMapping(
        identity_field="VM",
        fact_fields=MappingProxyType(
            {
                "power_state": "Powerstate",
                "cpu_count": "CPUs",
                "memory_mb": "Memory",
                "datacenter": "Datacenter",
                "cluster": "Cluster",
                "hypervisor_host": "Host",
            }
        ),
        resource_type="virtual-machine",
    ),
    "hvtools": SourceMapping(
        identity_field="VMName",
        fact_fields=MappingProxyType(
            {
                "power_state": "State",
                "generation": "Generation",
                "cpu_count": "CPUCount",
                "memory_bytes": "MemoryAssigned",
                "hypervisor_host": "Host",
            }
        ),
        resource_type="virtual-machine",
    ),
    "bom": SourceMapping(
        identity_field="name",
        fact_fields=MappingProxyType(
            {
                "component_type": "type",
                "component_version": "version",
                "license": "licenses[0].license.id",
            }
        ),
        resource_type="software-component",
    ),
}


def source_mapping(source_format: str) -> SourceMapping:
    """Return the mapping for ``source_format``.

    Raises ``KeyError`` for an unsupported format -- callers translate that
    into a domain error rather than guessing a mapping (fail closed).
    """
    return _SOURCE_MAPPINGS[source_format]


def supported_source_formats() -> tuple[str, ...]:
    return tuple(sorted(_SOURCE_MAPPINGS))


__all__ = ["SourceMapping", "source_mapping", "supported_source_formats"]
