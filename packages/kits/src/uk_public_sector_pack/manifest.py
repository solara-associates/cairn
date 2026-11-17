"""Manifest for the UK public sector landing-zone pack.

Per ADR-016, CAIRN launches with exactly one jurisdiction pack: the UK,
deployed in ``europe-west2``. This pack names the two pieces of existing
domain logic it is built on, rather than inventing new ones:

- R2-03's pattern catalogue -- specifically the already-published
  ``landing-zone`` pattern (``patterns/landing-zone.yaml``), grounded in
  CLOUD-ARCHITECTURE-PATTERNS.md's P14/P15.
- R5-05b's residency sweep (``cairn_modules.sovereignty.residency_sweep``),
  which already encodes ADR-016's UK/``europe-west2`` constraint.

Neither of ``PatternRepository`` nor the residency sweep is exposed as a
formal kernel ``Port`` protocol today (unlike, say,
``cairn_kernel.execution_gate.ports.ExecutionGatePort``) -- both are plain
functions in ``cairn_modules``. ``declared_ports`` below names the real,
importable entry points this pack actually calls, which is the honest
equivalent for a pack wired to domain functions rather than a formal port
interface; this module does not invent a ``Port`` class that does not
otherwise exist in this codebase just to have one to declare.

The pack performs no mutation of its own: it identifies which existing
pattern and residency rule apply to a UK public sector tenant. It does not
run Terraform, provision any resource, or change any state --
``MutationClass.READ_ONLY`` end to end, consistent with R0-R3's read-only
boundary.
"""

from __future__ import annotations

from cairn_kernel.hex.primitives import MutationClass
from cairn_kits.vertical_packs.manifest import PackManifest

MANIFEST = PackManifest(
    pack_id="uk-public-sector",
    version="2026.11.0",
    declared_ports=(
        "cairn_modules.sovereignty.residency_sweep.sweep_estate_residency",
        "cairn_modules.design.patterns.load_pattern",
    ),
    declared_mutation_classes=(MutationClass.READ_ONLY,),
)
