"""R3-08: sandbox policy for 729's "tests" validation adapter -- spec §16's
R3-08 row ("Add sandboxed execution (limits, no network by default)",
acceptance text "Resource and time limits enforced; egress blocked") and
ADR-010's rationale for why this matters even for a read-only check: running
a customer's own declared test suite, even against an isolated temp copy of
the *proposed* rewrite (never the customer's real checkout -- see
``cairn_modules.transformation.validation``'s module docstring), is still
arbitrary code execution. It must never reach the network or run unbounded
by default.

Of 729's three real ``ValidationPort`` adapters
(``cairn_adapters.validation_static``/``validation_tests``/
``validation_deps``), only ``validation_tests.real.TestSuiteValidationAdapter``
actually executes anything the customer declared: it discovers and runs the
repo's own ``make test``/``npm test``/``cargo test``/``pytest`` command
(``cairn_adapters.validation_tests.real.discover_test_command``). The static
adapter shells out to this repo's own deterministic, zero-dependency
``cairn-transform-validator-cli`` binary -- not customer code -- and the
dependency adapter never executes anything at all (a pure static import/
source scan, confirmed by reading
``packages/adapters/src/cairn_adapters/validation_deps/real.py``: no
``subprocess``, no ``exec``, no network import anywhere in it). Both are
already covered by the per-call ``timeout_seconds`` discipline
``cairn_adapters.transform_core.subprocess_adapter``/
``cairn_adapters.validation_static.subprocess_adapter`` already use for a
*known, fixed-shape, non-arbitrary* subprocess call; this unit does not
touch either of them. This module, and
``cairn_adapters.sandbox_runner``, exist for the "tests" adapter alone.

This module is the domain-layer policy: the limit values and their
invariants, with no OS-specific mechanism in it (that lives in
``cairn_adapters.sandbox_runner``, kept out of ``cairn_modules`` by the same
domain-purity import-linter contract (``.importlinter``'s
``domain-purity``) every other module in this package already respects --
``cairn_modules`` never imports ``cairn_adapters``).

No existing resource-limit mechanism exists anywhere else in this codebase
to reuse: ``cairn_adapters.scanners`` (the posture scanners -- steampipe/
opa/prowler) and every existing subprocess adapter
(``transform_core``/``validation_static``) use only a wall-clock
``subprocess.run(..., timeout=...)``, never ``resource.setrlimit`` or a
cgroup (grepped for ``setrlimit``/``RLIMIT``/``cgroup`` across ``packages/``
and ``apps/`` before writing this: no hits). This unit introduces the first
CPU/memory limit in the estate, and reuses the one convention that *does*
already exist (the wall-clock ``timeout=`` kwarg) for the time bound,
rather than inventing a second timeout mechanism alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A conservative bound for a customer's own declared test suite running
#: against a small, isolated temp copy of one transformation run's rewritten
#: files -- generous enough for a real `pytest`/`cargo test`/`npm test`
#: invocation on that small a tree, not generous enough to let a runaway
#: process (deliberate or not) consume the host indefinitely.
DEFAULT_CPU_SECONDS = 30
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024  # 512 MiB
DEFAULT_WALL_CLOCK_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """The resource and time bounds ``cairn_adapters.sandbox_runner``
    enforces around one sandboxed execution. Every field has an invariant
    enforced in the constructor (a non-positive limit is not "unlimited",
    it is a configuration error) -- the same "invariants enforced in
    constructors" discipline ``ValidationResult.__post_init__`` above
    already uses in this same package.

    There is deliberately no field to disable a limit, or to allow network
    egress: this unit was not asked to build an escape hatch, and
    ``cairn_adapters.sandbox_runner`` blocks egress unconditionally for
    every sandboxed execution, never behind a flag here or anywhere else.
    """

    cpu_seconds: int = DEFAULT_CPU_SECONDS
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS

    def __post_init__(self) -> None:
        if self.cpu_seconds <= 0:
            raise ValueError(f"cpu_seconds must be positive, got {self.cpu_seconds!r}")
        if self.memory_bytes <= 0:
            raise ValueError(f"memory_bytes must be positive, got {self.memory_bytes!r}")
        if self.wall_clock_seconds <= 0:
            raise ValueError(
                f"wall_clock_seconds must be positive, got {self.wall_clock_seconds!r}"
            )


#: The limits ``cairn_adapters.sandbox_runner.TestSuiteValidationAdapter``
#: uses when a caller does not override them.
DEFAULT_SANDBOX_LIMITS = SandboxLimits()


__all__ = [
    "DEFAULT_CPU_SECONDS",
    "DEFAULT_MEMORY_BYTES",
    "DEFAULT_SANDBOX_LIMITS",
    "DEFAULT_WALL_CLOCK_SECONDS",
    "SandboxLimits",
]
