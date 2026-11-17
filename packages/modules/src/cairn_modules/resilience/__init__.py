"""CAIRN cairn_modules.resilience: R5-05a failover rule evaluation.

Evaluates a workload's declared failover policy (primary/secondary target)
against a synthetic failure injection, on top of R1-06/R1-07's canonical
``Workload`` model. Pure domain model: no adapter, no I/O (``cairn_modules``
is a leaf consumer of ``cairn_kernel``/``cairn_contracts`` only, per
``.importlinter``'s ``domain-purity`` contract).
"""

from cairn_modules.resilience.model import (
    FailoverOutcome,
    FailoverPolicy,
    FailoverPolicyMap,
    FailoverResult,
    evaluate_estate_failover,
    evaluate_failover,
)

__all__ = [
    "FailoverOutcome",
    "FailoverPolicy",
    "FailoverPolicyMap",
    "FailoverResult",
    "evaluate_estate_failover",
    "evaluate_failover",
]
