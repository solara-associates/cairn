"""R3-05: the "tests" half of ``ValidationPort`` (spec §5.4) -- runs
whatever test suite the source repository already declares, read-only,
against an isolated temp copy of the proposed rewritten tree, never the
customer's real checkout. Plus a deterministic fake for tests."""

from cairn_adapters.validation_tests.fake import FakeTestSuiteValidationAdapter
from cairn_adapters.validation_tests.real import (
    TEST_SUITE_CHECK_ID,
    TestSuiteValidationAdapter,
)

__all__ = [
    "TEST_SUITE_CHECK_ID",
    "FakeTestSuiteValidationAdapter",
    "TestSuiteValidationAdapter",
]
