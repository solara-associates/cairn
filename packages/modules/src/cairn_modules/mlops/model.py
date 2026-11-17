"""R5-03a: MLOps model/artefact registry and drift detection.

A registry of versioned model entries (model id, version, an opaque
training-data reference, and a numeric metrics dict), and a drift check
that compares a registered baseline entry against a "current" snapshot of
the same shape (never a real serving call -- the snapshot is a fixture the
caller supplies, per the brief: "No cloud -- no real model training or
serving infrastructure exists or is implied").

Pure domain model: no adapter, no I/O (``cairn_modules`` is a leaf consumer
of ``cairn_kernel`` only, per ``.importlinter``'s ``domain-purity``
contract) -- same convention as ``cairn_modules.risk_policy`` and
``cairn_modules.finops``.

Judgement calls:

* **No persistence.** The brief says persistence is "NOT required ... if no
  existing pattern makes it trivial", and this unit's acceptance text only
  asks for registry round-trip (register/retrieve in the same process) and
  drift detection against a fixture snapshot -- neither needs the entry to
  survive a process restart. An in-memory, dataclass-based registry is the
  simplest thing that satisfies the acceptance criteria, so persistence is
  deliberately not added here; 817 (self-healing, which depends on 816) can
  add a ``persistence_postgres`` adapter behind a port later if it turns out
  to need one, following ``packages/adapters/src/cairn_adapters/
  persistence_postgres``'s existing migration pattern -- not invented here.
* **Boundary: a delta exactly at the threshold counts as drift.** This
  repo's existing policy layers fail closed on ambiguity (e.g.
  ``risk_policy.model``'s tier checks reject rather than silently default).
  A drift *threshold* is the maximum tolerated movement; treating a delta
  that exactly equals it as "not drifted" would mean the configured number
  is never actually enforced at its own boundary. So the comparison is
  ``abs(delta) >= threshold``, not ``>``.
* **Metric shape must match exactly.** The brief calls the current snapshot
  "same shape" as the baseline. Rather than silently ignoring an added or
  dropped metric (which could hide a real regression, e.g. a metric that
  disappeared because the new model no longer reports it), a shape mismatch
  raises ``ValidationError`` -- fail closed, same convention as everywhere
  else in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.errors import NotFoundError, ValidationError

DEFAULT_DRIFT_THRESHOLD = 0.1

# Guards the ">= threshold counts as drift" boundary (see the module
# docstring's boundary judgement call) against float round-off -- e.g.
# ``0.9 - 0.8`` is ``0.09999999999999998`` in binary floating point, not
# exactly ``0.1``, which would otherwise make a deliberate boundary case
# fail to register as drift by a fraction of a float ULP.
_BOUNDARY_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class ModelRegistryEntry:
    """One versioned registry entry.

    ``training_data_ref`` is an opaque identifier (e.g. a dataset hash or
    URI), never the actual training data -- the registry stores references,
    not payloads.
    """

    model_id: str
    version: str
    training_data_ref: str
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValidationError("registry entry requires a non-blank model_id")
        if not self.version.strip():
            raise ValidationError("registry entry requires a non-blank version")
        if not self.training_data_ref.strip():
            raise ValidationError("registry entry requires a non-blank training_data_ref")
        if not self.metrics:
            raise ValidationError("registry entry requires at least one metric")
        for name, value in self.metrics.items():
            if not name.strip():
                raise ValidationError("metric names must not be blank")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(
                    f"metric {name!r} must be numeric, got {type(value).__name__}"
                )

    @property
    def key(self) -> tuple[str, str]:
        return (self.model_id, self.version)


class ModelRegistry:
    """In-memory registry of ``ModelRegistryEntry`` keyed by (model_id,
    version). See the module docstring's "No persistence" judgement call
    for why this is dataclass/in-memory rather than backed by a store."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ModelRegistryEntry] = {}

    def register(self, entry: ModelRegistryEntry) -> None:
        if entry.key in self._entries:
            raise ValidationError(
                f"model {entry.model_id!r} version {entry.version!r} is already"
                " registered -- register a new version instead of overwriting one"
            )
        self._entries[entry.key] = entry

    def get(self, model_id: str, version: str) -> ModelRegistryEntry:
        entry = self._entries.get((model_id, version))
        if entry is None:
            raise NotFoundError(f"no registry entry for model {model_id!r} version {version!r}")
        return entry

    def list_versions(self, model_id: str) -> tuple[ModelRegistryEntry, ...]:
        return tuple(
            entry
            for (entry_model_id, _), entry in sorted(self._entries.items())
            if entry_model_id == model_id
        )


@dataclass(frozen=True, slots=True)
class MetricDrift:
    """How far one metric moved between baseline and current, and whether
    that movement exceeds the configured threshold."""

    metric: str
    baseline_value: float
    current_value: float
    delta: float
    threshold: float
    drifted: bool


@dataclass(frozen=True, slots=True)
class DriftReport:
    """The result of comparing a baseline entry against a current
    snapshot: every metric's movement, and whether any of them drifted."""

    model_id: str
    version: str
    metrics: tuple[MetricDrift, ...]

    @property
    def drifted(self) -> bool:
        return any(metric.drifted for metric in self.metrics)

    @property
    def drifted_metrics(self) -> tuple[MetricDrift, ...]:
        return tuple(metric for metric in self.metrics if metric.drifted)


def check_drift(
    baseline: ModelRegistryEntry,
    current_metrics: dict[str, float],
    *,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
    thresholds: dict[str, float] | None = None,
) -> DriftReport:
    """Compare ``current_metrics`` (a fixture "current" snapshot, same
    shape as the baseline's metrics -- never a real serving call) against
    ``baseline.metrics``.

    ``threshold`` is the default per-metric drift threshold; ``thresholds``
    optionally overrides it per metric name. A metric drifts when
    ``abs(current - baseline) >= threshold`` for that metric (see the
    module docstring's boundary judgement call: a delta exactly at the
    threshold counts as drift).
    """

    if threshold < 0:
        raise ValidationError("drift threshold must not be negative")
    per_metric_thresholds = dict(thresholds or {})
    for name, value in per_metric_thresholds.items():
        if value < 0:
            raise ValidationError(f"drift threshold for {name!r} must not be negative")

    baseline_keys = set(baseline.metrics)
    current_keys = set(current_metrics)
    if baseline_keys != current_keys:
        missing = baseline_keys - current_keys
        added = current_keys - baseline_keys
        raise ValidationError(
            "current snapshot does not match the baseline's metric shape"
            f" (missing={sorted(missing)}, added={sorted(added)})"
        )

    drifts: list[MetricDrift] = []
    for name in sorted(baseline.metrics):
        baseline_value = baseline.metrics[name]
        current_value = current_metrics[name]
        metric_threshold = per_metric_thresholds.get(name, threshold)
        delta = current_value - baseline_value
        drifts.append(
            MetricDrift(
                metric=name,
                baseline_value=baseline_value,
                current_value=current_value,
                delta=delta,
                threshold=metric_threshold,
                drifted=abs(delta) >= metric_threshold - _BOUNDARY_EPSILON,
            )
        )

    return DriftReport(
        model_id=baseline.model_id,
        version=baseline.version,
        metrics=tuple(drifts),
    )


__all__ = [
    "DEFAULT_DRIFT_THRESHOLD",
    "DriftReport",
    "MetricDrift",
    "ModelRegistry",
    "ModelRegistryEntry",
    "check_drift",
]
