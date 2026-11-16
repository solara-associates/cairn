"""R3-05: ``cairn_modules.transformation.validation`` -- the aggregation
layer over the three ``ValidationPort`` adapters, and the blocking gate
spec S16/R3-05's acceptance text requires ("failures block approval").

Each adapter's own real/fake parity is covered by
``packages/adapters/tests/test_validation_static.py``/
``test_validation_tests.py``/``test_validation_deps.py``. This module
only exercises the aggregation (``run_validation``) and the gate
(``require_validation_passed``) themselves, against hand-built
``ValidationPort`` stubs -- so a failure here can never be explained away
as "one adapter's own bug", only as this module's own aggregation/gating
logic.
"""

from __future__ import annotations

import pytest
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import ValidationError
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import (
    ManifestEdit,
    ManifestEntry,
    ManifestOutcome,
    TransformationManifest,
)
from cairn_modules.transformation.validation import (
    ValidationRequest,
    ValidationResult,
    ValidationRun,
    require_validation_passed,
    run_validation,
)

DETECTOR_VERSION = "cairn-detector/0.1.0"
PATTERN_VERSION = "cairn-hcl-parser/0.1.0"
PATCHER_VERSION = "cairn-transform-patcher/0.1.0"

S3_TF_CONTENT = 'resource "aws_s3_bucket" "b" {\n  acl = "public-read"\n}\n'


class _StubCheck:
    """A minimal ``ValidationPort`` stub: returns exactly the results it
    was constructed with, and records every request it was called with."""

    def __init__(self, results: tuple[ValidationResult, ...]) -> None:
        self._results = results
        self.calls: list[ValidationRequest] = []

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]:
        self.calls.append(request)
        return self._results


def _request(run_id: str = "run-1") -> ValidationRequest:
    source_file = SourceFile(path="s3.tf", content=S3_TF_CONTENT, language=SourceLanguage.TERRAFORM)
    entry = ManifestEntry(
        source_file_id="s3.tf",
        rule_id="tf-s3-bucket-inline-acl-deprecated",
        outcome=ManifestOutcome.APPLIED,
        reason=None,
        edits=(
            ManifestEdit(
                start_byte=33, end_byte=52, start_line=2, end_line=2, replacement='acl = "private"'
            ),
        ),
        detector_version=DETECTOR_VERSION,
        pattern_version=PATTERN_VERSION,
        patcher_version=PATCHER_VERSION,
    )
    manifest = TransformationManifest(source_file_ids=("s3.tf",), entries=(entry,))
    diff = render_transformation_diff(run_id=run_id, files=(source_file,), manifest=manifest)
    return ValidationRequest(run_id=run_id, files=(source_file,), manifest=manifest, diff=diff)


def test_run_validation_calls_every_check_and_aggregates_results_in_order() -> None:
    check_a = _StubCheck((ValidationResult(check_id="a", passed=True),))
    check_b = _StubCheck(
        (ValidationResult(check_id="b1", passed=True), ValidationResult(check_id="b2", passed=True))
    )
    request = _request()

    run = run_validation(request, checks=(check_a, check_b))

    assert run.run_id == "run-1"
    assert [result.check_id for result in run.results] == ["a", "b1", "b2"]
    assert check_a.calls == [request]
    assert check_b.calls == [request]


def test_run_validation_never_short_circuits_on_a_failing_check() -> None:
    failing = _StubCheck((ValidationResult(check_id="f", passed=False, reason="broke"),))
    passing = _StubCheck((ValidationResult(check_id="p", passed=True),))

    run = run_validation(_request(), checks=(failing, passing))

    assert [result.check_id for result in run.results] == ["f", "p"]
    assert passing.calls, "a later check must still be called after an earlier one fails"


def test_validation_run_approved_is_true_only_when_every_result_passed() -> None:
    all_pass = ValidationRun(
        run_id="r", results=(ValidationResult(check_id="a", passed=True),)
    )
    one_fails = ValidationRun(
        run_id="r",
        results=(
            ValidationResult(check_id="a", passed=True),
            ValidationResult(check_id="b", passed=False, reason="nope"),
        ),
    )
    empty = ValidationRun(run_id="r", results=())

    assert all_pass.approved is True
    assert one_fails.approved is False
    assert empty.approved is True
    assert one_fails.failed_results == (ValidationResult(check_id="b", passed=False, reason="nope"),)


def test_a_failing_validation_check_actually_blocks_the_gate() -> None:
    """The acceptance text itself, proven directly: ``require_validation_
    passed`` raises -- it does not just report a false boolean a caller
    could ignore."""

    run = ValidationRun(
        run_id="run-1",
        results=(
            ValidationResult(check_id="static-reparse", passed=True),
            ValidationResult(check_id="tests", passed=False, reason="pytest exited 1"),
        ),
    )

    with pytest.raises(ValidationError) as exc_info:
        require_validation_passed(run)

    assert "run-1" in str(exc_info.value)
    assert "tests" in str(exc_info.value)
    assert "pytest exited 1" in str(exc_info.value)


def test_a_fully_passing_validation_run_is_not_blocked() -> None:
    run = ValidationRun(
        run_id="run-1",
        results=(
            ValidationResult(check_id="static-reparse", passed=True),
            ValidationResult(check_id="tests", passed=True),
            ValidationResult(check_id="dependency-manifest", passed=True),
        ),
    )

    # Must not raise.
    require_validation_passed(run)


def test_validation_result_requires_a_reason_when_failed() -> None:
    with pytest.raises(ValueError):
        ValidationResult(check_id="x", passed=False, reason=None)


def test_validation_result_may_omit_a_reason_when_passed() -> None:
    result = ValidationResult(check_id="x", passed=True)
    assert result.reason is None
