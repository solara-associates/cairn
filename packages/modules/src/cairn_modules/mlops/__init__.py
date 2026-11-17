"""R5-03a: MLOps model/artefact registry and drift detection.

A versioned registry of model entries (model id, version, an opaque
training-data reference, and a numeric metrics dict) and a drift check
that flags metrics whose movement between a baseline entry and a current
snapshot exceeds a configured threshold. Pure domain model: no adapter, no
I/O (``cairn_modules`` is a leaf consumer of ``cairn_kernel`` only, per
``.importlinter``'s ``domain-purity`` contract).
"""

from cairn_modules.mlops.model import (
    DEFAULT_DRIFT_THRESHOLD,
    DriftReport,
    MetricDrift,
    ModelRegistry,
    ModelRegistryEntry,
    check_drift,
)

__all__ = [
    "DEFAULT_DRIFT_THRESHOLD",
    "DriftReport",
    "MetricDrift",
    "ModelRegistry",
    "ModelRegistryEntry",
    "check_drift",
]
