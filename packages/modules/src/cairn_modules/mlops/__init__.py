"""R5-03a/R5-03b: MLOps model/artefact registry, drift detection, and
bounded self-healing.

A versioned registry of model entries (model id, version, an opaque
training-data reference, and a numeric metrics dict), a drift check that
flags metrics whose movement between a baseline entry and a current
snapshot exceeds a configured threshold, and bounded self-healing trigger
logic that decides whether a retrain/rollback responding to detected drift
is allowed right now or must escalate to a human decision. Pure domain
model: no adapter, no I/O (``cairn_modules`` is a leaf consumer of
``cairn_kernel`` only, per ``.importlinter``'s ``domain-purity`` contract).
"""

from cairn_modules.mlops.model import (
    DEFAULT_DRIFT_THRESHOLD,
    DriftReport,
    MetricDrift,
    ModelRegistry,
    ModelRegistryEntry,
    check_drift,
)
from cairn_modules.mlops.self_healing import (
    SELF_HEALING_MUTATION_CLASS,
    SelfHealingActionRecord,
    SelfHealingActionType,
    SelfHealingBoundExceededError,
    SelfHealingBounds,
    SelfHealingDecision,
    evaluate_self_healing_trigger,
)

__all__ = [
    "DEFAULT_DRIFT_THRESHOLD",
    "SELF_HEALING_MUTATION_CLASS",
    "DriftReport",
    "MetricDrift",
    "ModelRegistry",
    "ModelRegistryEntry",
    "SelfHealingActionRecord",
    "SelfHealingActionType",
    "SelfHealingBoundExceededError",
    "SelfHealingBounds",
    "SelfHealingDecision",
    "check_drift",
    "evaluate_self_healing_trigger",
]
