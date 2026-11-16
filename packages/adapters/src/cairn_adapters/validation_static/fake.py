"""R3-05: the fake/deterministic-test static ``ValidationPort`` adapter.

Same registration discipline ``cairn_adapters.transform_core.fake.
FakeTransformationPort``/``cairn_adapters.source_git.fake.
FakeRepositorySource`` already use: a test registers the exact
``ValidationResult`` tuple this fake returns for a given ``run_id``, and
gets it back verbatim -- no subprocess, no Rust binary, no filesystem
access at all.
"""

from __future__ import annotations

from cairn_kernel.errors import NotFoundError
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult


class FakeStaticValidationAdapter:
    """Deterministic static ``ValidationPort`` for tests.

    ``calls`` records every ``ValidationRequest`` this adapter was asked
    to validate, in call order, so a test can assert it was invoked with
    the expected request without depending on a real subprocess.
    """

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
                f"no static validation fixture registered for run {request.run_id!r}"
            )
        return self._fixtures[request.run_id]


__all__ = ["FakeStaticValidationAdapter"]
