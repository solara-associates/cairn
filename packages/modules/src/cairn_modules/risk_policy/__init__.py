"""R4-01: the risk-tier policy engine (ADR-010).

Decides which risk tier applies to a mutation class and enforces that
tier's approver-role and field requirements before an approval can be
authorized -- a policy layer on top of R1-21's approval/execution state
machines and the R-MUT-01/R-MUT-02 conformance rules, not a replacement for
them. Pure domain model: no adapter, no I/O (``cairn_modules`` is a leaf
consumer of ``cairn_kernel`` only, per ``.importlinter``'s ``domain-purity``
contract).
"""

from cairn_modules.risk_policy.model import (
    BLAST_RADIUS_CONFIRMER_ROLE,
    EXECUTION_ROLE,
    NON_APPROVER_ROLES,
    TIER_BY_MUTATION_CLASS,
    ApproverSignOff,
    BlastRadiusConfirmation,
    PreflightResult,
    PreflightStatus,
    RiskAcceptance,
    RiskTier,
    authorize_tier,
    tier_for_approval,
    tier_for_mutation_class,
)

__all__ = [
    "BLAST_RADIUS_CONFIRMER_ROLE",
    "EXECUTION_ROLE",
    "NON_APPROVER_ROLES",
    "TIER_BY_MUTATION_CLASS",
    "ApproverSignOff",
    "BlastRadiusConfirmation",
    "PreflightResult",
    "PreflightStatus",
    "RiskAcceptance",
    "RiskTier",
    "authorize_tier",
    "tier_for_approval",
    "tier_for_mutation_class",
]
