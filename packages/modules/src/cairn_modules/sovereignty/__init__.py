"""CAIRN cairn_modules.sovereignty: R5-05b estate-data-level residency sweeps.

Flags any workload in a canonical estate snapshot whose declared region
falls outside the active jurisdiction pack's residency constraint (ADR-016:
UK-only, ``europe-west2``, at launch), and seals the sweep's result as
evidence through ``cairn_kernel.evidence.seal_evidence``. Pure domain
model: no adapter, no I/O, no cloud inventory call (``cairn_modules`` is a
leaf consumer of ``cairn_kernel``/``cairn_contracts`` only, per
``.importlinter``'s ``domain-purity`` contract).
"""

from cairn_modules.sovereignty.residency_sweep import (
    EVIDENCE_SUBJECT_KIND,
    PRODUCER,
    REGION_FACT_KEY,
    UK_ALLOWED_REGIONS,
    UK_PACK_ID,
    UK_PACK_VERSION,
    ResidencyFinding,
    ResidencyFindingReason,
    ResidencySweepResult,
    ResidencySweepStatus,
    build_residency_sweep_evidence_package,
    region_fact,
    sweep_estate_residency,
)

__all__ = [
    "EVIDENCE_SUBJECT_KIND",
    "PRODUCER",
    "REGION_FACT_KEY",
    "UK_ALLOWED_REGIONS",
    "UK_PACK_ID",
    "UK_PACK_VERSION",
    "ResidencyFinding",
    "ResidencyFindingReason",
    "ResidencySweepResult",
    "ResidencySweepStatus",
    "build_residency_sweep_evidence_package",
    "region_fact",
    "sweep_estate_residency",
]
