"""R3-05: validation adapters (static, tests, dependency) -- spec S16's
R3-05 row ("Implement validation adapters (static, tests, dependency)",
acceptance text "Results per check; failures block approval") and spec
§5.4's ``ValidationPort | transformation | test/static runner, fake`` row.

This module is the aggregation layer: it defines the one shared port
(``ValidationPort``) every adapter in ``cairn_adapters.validation_static``/
``validation_tests``/``validation_deps`` implements, the one shared result
shape (``ValidationResult``), and the function (``run_validation``) that
calls every configured check for a given transformation run and combines
their results into one ``ValidationRun``.

Validation runs against the *proposed* change, never an applied one
(``~/solara/lz2026/s726-handover.md``: 726's own ``TransformationPort`` has
"no write-back of any kind"; 728's diff artefact "never writes to any path
on disk" either). This module inherits that discipline by construction:
every input type below (``ValidationRequest``) carries only in-memory
``SourceFile``/``TransformationManifest``/``TransformationDiff`` values --
never a filesystem path to a customer's real checkout -- so nothing a
``ValidationPort`` adapter does here can touch a real file, this unit's or
any later one's.

Blocking, not advisory (spec S16/R3-05: "failures block approval"):
``require_validation_passed`` is the actual control a caller must pass
through before treating a run as approved -- it raises
``cairn_kernel.errors.ValidationError`` when any check failed, rather than
returning a boolean a caller could silently ignore. ``ValidationRun.
approved`` is also available for a caller (like the API route below) that
wants to report the outcome without raising, but the one way to *proceed
past* a failed validation is to not call the gate at all -- there is no
"proceed anyway" parameter on ``require_validation_passed``, the same
"the interface itself has no such method" discipline ``RepositorySourcePort``
and ``TransformationPort`` already use for their own "never writes back"
guarantees. A later unit (731's sandbox) wraps these same adapters; it is
expected to call this same gate before treating a run as safe to execute,
not to invent its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cairn_contracts.transformation import SourceFile
from cairn_kernel.errors import ValidationError
from cairn_kernel.hex import Port

from cairn_modules.transformation.diff import TransformationDiff
from cairn_modules.transformation.engine import TransformationManifest


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """One check's outcome. Mirrors ``cairn_transform_validator::
    ValidationResult`` (Rust) field-for-field, deliberately: the static
    adapter's real subprocess reads that exact JSON shape back into this
    dataclass with no translation table to keep in sync by hand (the same
    "shared contract" discipline ``cairn_modules.transformation.engine.
    build_manifest`` already uses for 726's ``CliOutput``).

    Invariant: a failed result always carries a reason naming why. A
    passed result may optionally carry one too (e.g. "no declared test
    suite found; nothing to run") -- unlike 725's ``ChangeEntry``, a pass
    here is not always silent, because "nothing to check" is itself worth
    reporting to a reviewer, not just a bare true/false.
    """

    check_id: str
    passed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.passed and self.reason is None:
            raise ValueError(
                f"a failed ValidationResult (check_id={self.check_id!r}) must carry a reason"
            )


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """Everything one ``ValidationPort`` adapter may need to validate one
    transformation run's *proposed* change. Every field is an in-memory
    value another unit already computed -- 721's fetched ``SourceFile``
    sequence, 726's ``TransformationManifest``, 728's rendered
    ``TransformationDiff`` -- never a filesystem path. An adapter that only
    needs one or two of these (the static adapter only reads ``manifest``
    and the matching ``SourceFile``'s content; the dependency adapter only
    reads ``files``/``diff``) simply ignores the rest; no adapter gains the
    ability to reach outside this request's own in-memory data.
    """

    run_id: str
    files: tuple[SourceFile, ...]
    manifest: TransformationManifest
    diff: TransformationDiff


class ValidationPort(Port, Protocol):
    """Spec §5.4's ``ValidationPort``. One method, run by the aggregation
    layer below once per configured check -- a static adapter, a test-suite
    adapter, and a dependency adapter all satisfy this same protocol
    (``cairn_adapters.validation_static``/``validation_tests``/
    ``validation_deps``), each returning its own ``ValidationResult``
    tuple. There is no write method on this port, by the same construction
    ``RepositorySourcePort``/``TransformationPort`` already use: a check can
    only ever report results, never mutate ``request`` or anything it
    points to."""

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]: ...


@dataclass(frozen=True, slots=True)
class ValidationRun:
    """The aggregated outcome of every configured check for one run."""

    run_id: str
    results: tuple[ValidationResult, ...]

    @property
    def approved(self) -> bool:
        """``True`` iff every check passed. ``all()`` over an empty
        sequence is ``True`` by Python's own definition -- a run given no
        checks at all is vacuously approved, the same way an empty
        ``ChangeSet``/``TransformationManifest`` is a legitimate "nothing
        to report" elsewhere in this codebase, never an error."""

        return all(result.passed for result in self.results)

    @property
    def failed_results(self) -> tuple[ValidationResult, ...]:
        return tuple(result for result in self.results if not result.passed)


def run_validation(
    request: ValidationRequest, *, checks: tuple[ValidationPort, ...]
) -> ValidationRun:
    """Call every configured ``ValidationPort`` check for ``request`` and
    aggregate their results in the order ``checks`` was given. Never
    short-circuits on a failing check -- a reviewer needs to see every
    check's outcome, not just the first failure (spec S16/R3-05: "Results
    per check")."""

    results: list[ValidationResult] = []
    for check in checks:
        results.extend(check.validate(request))
    return ValidationRun(run_id=request.run_id, results=tuple(results))


def require_validation_passed(run: ValidationRun) -> None:
    """The blocking gate spec S16/R3-05's acceptance text names:
    "failures block approval". Raises ``ValidationError`` -- never returns
    a boolean -- when any check in ``run`` failed, so a caller cannot
    accidentally ignore the outcome and proceed anyway; a caller that wants
    to proceed past a failed run has no argument on this function that lets
    it. Returns ``None`` (does nothing) when every check passed.
    """

    if run.approved:
        return
    reasons = "; ".join(
        f"{result.check_id}: {result.reason}" for result in run.failed_results
    )
    raise ValidationError(
        f"transformation run {run.run_id} failed validation and cannot be approved: {reasons}"
    )


__all__ = [
    "ValidationPort",
    "ValidationRequest",
    "ValidationResult",
    "ValidationRun",
    "require_validation_passed",
    "run_validation",
]
