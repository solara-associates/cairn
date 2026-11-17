"""R5-03a: the MLOps model registry and drift-detection module.

Covers registry round-trip, zero drift on an identical snapshot, real
drift on a deliberately altered snapshot (naming the drifted metric and
its delta), and the boundary case where a delta lands exactly on the
configured threshold -- documented in ``cairn_modules.mlops.model`` as
counting as drift (fail closed at the boundary, same convention as this
codebase's other policy layers).
"""

import pytest
from cairn_kernel.errors import NotFoundError, ValidationError
from cairn_modules.mlops.model import (
    ModelRegistry,
    ModelRegistryEntry,
    check_drift,
)


def _entry(**overrides: object) -> ModelRegistryEntry:
    fields: dict[str, object] = {
        "model_id": "risk-scorer",
        "version": "1.0.0",
        "training_data_ref": "dataset:2026-10-snapshot:sha256:abc123",
        "metrics": {"accuracy": 0.92, "latency_p50": 120.0},
    }
    fields.update(overrides)
    return ModelRegistryEntry(**fields)  # type: ignore[arg-type]


def test_registry_round_trip() -> None:
    registry = ModelRegistry()
    entry = _entry()

    registry.register(entry)
    retrieved = registry.get("risk-scorer", "1.0.0")

    assert retrieved is entry
    assert retrieved.model_id == "risk-scorer"
    assert retrieved.version == "1.0.0"
    assert retrieved.training_data_ref == "dataset:2026-10-snapshot:sha256:abc123"
    assert retrieved.metrics == {"accuracy": 0.92, "latency_p50": 120.0}


def test_registry_rejects_duplicate_version() -> None:
    registry = ModelRegistry()
    registry.register(_entry())

    with pytest.raises(ValidationError):
        registry.register(_entry())


def test_registry_get_missing_raises_not_found() -> None:
    registry = ModelRegistry()

    with pytest.raises(NotFoundError):
        registry.get("risk-scorer", "9.9.9")


def test_registry_lists_versions_for_model_sorted() -> None:
    registry = ModelRegistry()
    registry.register(_entry(version="2.0.0"))
    registry.register(_entry(version="1.0.0"))
    registry.register(_entry(model_id="other-model", version="1.0.0"))

    versions = tuple(e.version for e in registry.list_versions("risk-scorer"))

    assert versions == ("1.0.0", "2.0.0")


def test_entry_requires_non_blank_fields() -> None:
    with pytest.raises(ValidationError):
        _entry(model_id="")
    with pytest.raises(ValidationError):
        _entry(version="  ")
    with pytest.raises(ValidationError):
        _entry(training_data_ref="")


def test_entry_requires_at_least_one_metric() -> None:
    with pytest.raises(ValidationError):
        _entry(metrics={})


def test_entry_rejects_non_numeric_metric() -> None:
    with pytest.raises(ValidationError):
        _entry(metrics={"accuracy": "high"})  # type: ignore[dict-item]


def test_drift_reports_zero_drift_on_identical_snapshot() -> None:
    baseline = _entry()

    report = check_drift(baseline, dict(baseline.metrics), threshold=0.1)

    assert report.drifted is False
    assert report.drifted_metrics == ()
    assert {m.metric: m.delta for m in report.metrics} == {
        "accuracy": 0.0,
        "latency_p50": 0.0,
    }


def test_drift_reports_real_drift_on_altered_snapshot() -> None:
    baseline = _entry(metrics={"accuracy": 0.92, "latency_p50": 120.0})
    current = {"accuracy": 0.70, "latency_p50": 121.0}  # accuracy dropped hard

    report = check_drift(baseline, current, threshold=0.1, thresholds={"latency_p50": 5.0})

    assert report.drifted is True
    drifted_names = {m.metric for m in report.drifted_metrics}
    assert drifted_names == {"accuracy"}
    accuracy_drift = next(m for m in report.metrics if m.metric == "accuracy")
    assert accuracy_drift.delta == pytest.approx(-0.22)
    assert accuracy_drift.drifted is True
    latency_drift = next(m for m in report.metrics if m.metric == "latency_p50")
    assert latency_drift.delta == pytest.approx(1.0)
    assert latency_drift.drifted is False


def test_drift_boundary_delta_exactly_at_threshold_counts_as_drift() -> None:
    baseline = _entry(metrics={"accuracy": 0.90})
    current = {"accuracy": 0.80}  # delta == -0.10, exactly the threshold

    report = check_drift(baseline, current, threshold=0.1)

    assert report.drifted is True
    assert report.metrics[0].delta == pytest.approx(-0.1)
    assert report.metrics[0].drifted is True


def test_drift_boundary_delta_just_under_threshold_is_not_drift() -> None:
    baseline = _entry(metrics={"accuracy": 0.90})
    current = {"accuracy": 0.801}  # delta == -0.099, just under the threshold

    report = check_drift(baseline, current, threshold=0.1)

    assert report.drifted is False


def test_drift_rejects_snapshot_with_mismatched_metric_shape() -> None:
    baseline = _entry(metrics={"accuracy": 0.9, "latency_p50": 100.0})

    with pytest.raises(ValidationError):
        check_drift(baseline, {"accuracy": 0.9})  # missing latency_p50

    with pytest.raises(ValidationError):
        check_drift(
            baseline,
            {"accuracy": 0.9, "latency_p50": 100.0, "extra": 1.0},
        )  # added metric


def test_drift_supports_per_metric_threshold_override() -> None:
    baseline = _entry(metrics={"accuracy": 0.9, "latency_p50": 100.0})
    current = {"accuracy": 0.85, "latency_p50": 103.0}

    report = check_drift(
        baseline,
        current,
        threshold=0.1,
        thresholds={"latency_p50": 2.0},
    )

    assert report.drifted is True
    drifted_names = {m.metric for m in report.drifted_metrics}
    assert drifted_names == {"latency_p50"}


def test_drift_rejects_negative_threshold() -> None:
    baseline = _entry()

    with pytest.raises(ValidationError):
        check_drift(baseline, dict(baseline.metrics), threshold=-0.1)
