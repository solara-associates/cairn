"""R3-05: the fake/deterministic-test "tests" ``ValidationPort`` adapter.

Same registration discipline every other fake in this codebase uses: no
temp directory, no subprocess, no filesystem access at all.
"""

from __future__ import annotations

from cairn_kernel.errors import NotFoundError
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult


class FakeTestSuiteValidationAdapter:
    """Deterministic "tests" ``ValidationPort`` for tests. ``calls``
    records every ``ValidationRequest`` this adapter was asked to
    validate, in call order."""

    def __init__(
        self, fixtures: dict[str, tuple[ValidationResult, ...]] | None = None
    ) -> None:
        self._fixtures: dict[str, tuple[ValidationResult, ...]] = dict(fixtures or {})
        self.calls: list[ValidationRequest] = []

    def register(self, run_id: str, results: tuple[ValidationResult, ...]) -> None:
        self._fixtures[run_id] = tuple(results)

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]:
        self.calls.append(request)
        if request.run_id not in self._fixtures:
            raise NotFoundError(
                f"no test-suite validation fixture registered for run {request.run_id!r}"
            )
        return self._fixtures[request.run_id]


__all__ = ["FakeTestSuiteValidationAdapter"]
