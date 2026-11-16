"""R3-05: the "tests" ``ValidationPort`` adapter -- real and fake, their
parity, and the construction-proof requirement the brief's step 5 names
explicitly: this adapter must never touch the customer's real checkout,
only an isolated temp copy.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

import pytest
from cairn_adapters.validation_tests import (
    TEST_SUITE_CHECK_ID,
    FakeTestSuiteValidationAdapter,
    TestSuiteValidationAdapter,
)
from cairn_adapters.validation_tests.real import _TEMP_DIR_PREFIX, discover_test_command
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import NotFoundError
from cairn_modules.transformation.diff import render_transformation_diff
from cairn_modules.transformation.engine import TransformationManifest
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult


def _request_with_files(files: tuple[SourceFile, ...], run_id: str = "run-1") -> ValidationRequest:
    manifest = TransformationManifest(source_file_ids=(), entries=())
    diff = render_transformation_diff(run_id=run_id, files=files, manifest=manifest)
    return ValidationRequest(run_id=run_id, files=files, manifest=manifest, diff=diff)


def test_no_declared_test_suite_is_a_pass_not_a_fabricated_failure() -> None:
    files = (SourceFile(path="README.md", content="hello\n", language=SourceLanguage.UNSUPPORTED),)
    adapter = TestSuiteValidationAdapter()
    results = adapter.validate(_request_with_files(files))
    assert len(results) == 1
    assert results[0].check_id == TEST_SUITE_CHECK_ID
    assert results[0].passed is True
    assert "no declared test suite" in results[0].reason


def test_a_declared_makefile_test_target_runs_and_passes() -> None:
    files = (
        SourceFile(
            path="Makefile",
            content="test:\n\t@exit 0\n",
            language=SourceLanguage.UNSUPPORTED,
        ),
    )
    adapter = TestSuiteValidationAdapter()
    results = adapter.validate(_request_with_files(files))
    assert len(results) == 1
    assert results[0].passed is True, results[0]
    assert results[0].check_id == TEST_SUITE_CHECK_ID


def test_a_declared_test_suite_that_attempts_network_egress_observes_it_blocked() -> None:
    """R3-08 (731): the adapter's own execution step now runs through
    ``cairn_adapters.sandbox_runner``, not a bare subprocess -- a declared
    test suite that actually tries to reach the network (not merely
    asserting a config flag) observes the attempt fail. The declared
    command here is ``python3 -m pytest`` -- a direct, single-hop exec
    of the discovered command, the same shape
    ``test_sandbox_runner.py``'s own fixtures use, deliberately not a
    ``make``/shell-wrapped command: ``cairn_adapters.sandbox_runner``'s
    own module docstring documents that this unit's macOS dev-loop
    mechanism (``DYLD_INSERT_LIBRARIES``) only covers the directly
    exec'd process, not a shell's further grandchildren, which is a
    platform-specific gap this test deliberately does not exercise --
    ``test_sandbox_runner.py``'s own tests are the ones that prove the
    block itself; this test proves it reaches through this adapter's
    real wiring to that mechanism, end to end, for the shape of command
    the adapter itself discovers.

    Skipped only if this environment has no outbound network at all to
    prove the control against (same discipline as
    ``test_sandbox_runner.py``'s negative control)."""

    import socket

    try:
        with socket.create_connection(("1.1.1.1", 80), timeout=3):
            pass
    except OSError:
        pytest.skip("no outbound network reachable from this test environment at all")

    test_file_content = (
        "import socket\n"
        "\n"
        "def test_egress_is_blocked_by_the_sandbox():\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 80), timeout=5)\n"
        "    except OSError:\n"
        "        return\n"
        "    raise AssertionError('reached the network from inside the sandbox')\n"
    )
    files = (
        SourceFile(
            path="test_egress.py", content=test_file_content, language=SourceLanguage.PYTHON
        ),
    )
    adapter = TestSuiteValidationAdapter()
    results = adapter.validate(_request_with_files(files))

    assert results[0].passed is True, (
        "the declared test suite's own assertion that network egress is blocked did "
        f"not pass -- the sandbox did not actually block the connection attempt: {results[0]}"
    )


def test_a_declared_makefile_test_target_that_fails_blocks() -> None:
    files = (
        SourceFile(
            path="Makefile",
            content="test:\n\t@exit 1\n",
            language=SourceLanguage.UNSUPPORTED,
        ),
    )
    adapter = TestSuiteValidationAdapter()
    results = adapter.validate(_request_with_files(files))
    assert results[0].passed is False
    assert results[0].reason is not None
    assert "exited 1" in results[0].reason or "make" in results[0].reason


def test_discover_test_command_prefers_makefile_over_pytest_layout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        assert discover_test_command(root) == ("make", "test")


def test_discover_test_command_returns_none_when_nothing_declares_a_suite() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        assert discover_test_command(Path(tmp)) is None


def test_fake_adapter_replays_registered_results() -> None:
    fake_adapter = FakeTestSuiteValidationAdapter()
    request = _request_with_files(())
    results = (ValidationResult(check_id=TEST_SUITE_CHECK_ID, passed=True),)
    fake_adapter.register(request.run_id, results)
    assert fake_adapter.validate(request) == results
    assert fake_adapter.calls == [request]


def test_fake_adapter_raises_for_an_unregistered_run() -> None:
    fake_adapter = FakeTestSuiteValidationAdapter()
    with pytest.raises(NotFoundError):
        fake_adapter.validate(_request_with_files(()))


# --- Construction proof: never the customer's real checkout -----------------


def test_validation_request_carries_no_filesystem_path_field() -> None:
    """``ValidationRequest`` -- the only input this adapter's public API
    accepts -- has no field through which a path to a pre-existing,
    real-on-disk checkout could ever be passed in. Every field is an
    in-memory value (``SourceFile``/``TransformationManifest``/
    ``TransformationDiff``), never a ``Path``/``str`` naming a directory
    on disk."""

    # ``ValidationRequest`` is defined under ``from __future__ import
    # annotations``, so ``field.type`` is the annotation's source text,
    # not a resolved class -- checked as a string for exactly that
    # reason, not by identity against ``pathlib.Path``.
    for field in dataclasses.fields(ValidationRequest):
        assert "Path" not in str(field.type), (
            f"ValidationRequest.{field.name} (annotated {field.type!r}) must never be a "
            "filesystem path -- the tests adapter must only ever see in-memory content, "
            "never a pointer to the customer's real checkout"
        )


def test_real_adapter_creates_and_removes_its_own_temp_directory_per_call(monkeypatch) -> None:
    created_dirs: list[Path] = []
    original_init = tempfile.TemporaryDirectory.__enter__

    def _recording_enter(self):
        path = original_init(self)
        created_dirs.append(Path(path))
        return path

    monkeypatch.setattr(tempfile.TemporaryDirectory, "__enter__", _recording_enter)

    files = (SourceFile(path="a.py", content="x = 1\n", language=SourceLanguage.PYTHON),)
    adapter = TestSuiteValidationAdapter()
    adapter.validate(_request_with_files(files))

    assert len(created_dirs) == 1, "exactly one temp directory per validate() call"
    assert created_dirs[0].name.startswith(_TEMP_DIR_PREFIX)
    assert not created_dirs[0].exists(), "the temp directory must be removed once validate() returns"


def test_real_adapter_never_reuses_a_directory_across_two_calls(monkeypatch) -> None:
    created_dirs: list[Path] = []
    original_init = tempfile.TemporaryDirectory.__enter__

    def _recording_enter(self):
        path = original_init(self)
        created_dirs.append(Path(path))
        return path

    monkeypatch.setattr(tempfile.TemporaryDirectory, "__enter__", _recording_enter)

    files = (SourceFile(path="a.py", content="x = 1\n", language=SourceLanguage.PYTHON),)
    adapter = TestSuiteValidationAdapter()
    adapter.validate(_request_with_files(files, run_id="run-a"))
    adapter.validate(_request_with_files(files, run_id="run-b"))

    assert len(created_dirs) == 2
    assert created_dirs[0] != created_dirs[1]
