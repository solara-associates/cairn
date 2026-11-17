"""The manifest contract every vertical accelerator pack must declare.

A conformant pack exposes, in its ``manifest`` submodule (see
``cairn_kits.vertical_packs.conventions``), a module-level ``MANIFEST``
attribute built from :class:`PackManifest`. Declared mutation classes reuse
ADR-010's existing ``MutationClass`` enum from the kernel — this module does
not invent a parallel taxonomy.

Validation here is structural only (right types, non-empty required
fields). It does not know whether a declared port or mutation class is
actually used correctly by the pack's code; that is out of scope for a
manifest check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.hex.primitives import MutationClass


@dataclass(frozen=True, slots=True)
class PackManifest:
    """A vertical accelerator pack's self-declaration.

    Attributes:
        pack_id: Stable identifier for the pack, e.g. ``"uk-public-sector"``.
        version: The pack's own version string.
        declared_ports: Import paths/names of the kernel/contract ports the
            pack uses. May be empty for a pack that uses none.
        declared_mutation_classes: The ``MutationClass`` values the pack's
            mutations fall under. Empty if the pack performs no mutations.
    """

    pack_id: str
    version: str
    declared_ports: tuple[str, ...] = field(default_factory=tuple)
    declared_mutation_classes: tuple[MutationClass, ...] = field(default_factory=tuple)


def validate_manifest_fields(manifest: PackManifest) -> list[str]:
    """Return a list of human-readable problems, empty if the manifest is valid."""
    errors: list[str] = []

    if not isinstance(manifest.pack_id, str) or not manifest.pack_id.strip():
        errors.append("pack_id must be a non-empty string")

    if not isinstance(manifest.version, str) or not manifest.version.strip():
        errors.append("version must be a non-empty string")

    if not isinstance(manifest.declared_ports, tuple) or not all(
        isinstance(port, str) and port.strip() for port in manifest.declared_ports
    ):
        errors.append("declared_ports must be a tuple of non-empty strings")

    if not isinstance(manifest.declared_mutation_classes, tuple) or not all(
        isinstance(mutation_class, MutationClass)
        for mutation_class in manifest.declared_mutation_classes
    ):
        errors.append("declared_mutation_classes must be a tuple of MutationClass values")

    return errors
