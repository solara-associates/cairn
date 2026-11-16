"""R3-08: ``cairn_modules.transformation.sandbox`` -- the domain-layer
``SandboxLimits`` policy. Pure invariant tests; the OS-level mechanism
itself is ``cairn_adapters.sandbox_runner``'s job and is tested in
``packages/adapters/tests/test_sandbox_runner.py``.
"""

from __future__ import annotations

import pytest
from cairn_modules.transformation.sandbox import (
    DEFAULT_CPU_SECONDS,
    DEFAULT_MEMORY_BYTES,
    DEFAULT_SANDBOX_LIMITS,
    DEFAULT_WALL_CLOCK_SECONDS,
    SandboxLimits,
)


def test_default_sandbox_limits_match_the_documented_defaults() -> None:
    assert DEFAULT_SANDBOX_LIMITS.cpu_seconds == DEFAULT_CPU_SECONDS
    assert DEFAULT_SANDBOX_LIMITS.memory_bytes == DEFAULT_MEMORY_BYTES
    assert DEFAULT_SANDBOX_LIMITS.wall_clock_seconds == DEFAULT_WALL_CLOCK_SECONDS


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_seconds", 0),
        ("cpu_seconds", -1),
        ("memory_bytes", 0),
        ("memory_bytes", -1),
        ("wall_clock_seconds", 0),
        ("wall_clock_seconds", -0.5),
    ],
)
def test_a_non_positive_limit_is_a_construction_error_not_unlimited(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        SandboxLimits(**{field: value})


def test_sandbox_limits_is_frozen() -> None:
    limits = SandboxLimits()
    with pytest.raises(AttributeError):
        limits.cpu_seconds = 5  # type: ignore[misc]


def test_sandbox_limits_has_no_field_to_allow_network_egress() -> None:
    """Construction-proof: there is no parameter on ``SandboxLimits`` that
    could ever enable network egress -- the block is unconditional, in
    ``cairn_adapters.sandbox_runner``, never a flag here."""

    import dataclasses

    field_names = {field.name for field in dataclasses.fields(SandboxLimits)}
    assert field_names == {"cpu_seconds", "memory_bytes", "wall_clock_seconds"}
