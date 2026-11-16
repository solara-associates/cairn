"""R3-05: the real "tests" ``ValidationPort`` adapter.

Spec §5.4: ``ValidationPort | transformation | test/static runner,
fake``. This is the "test runner" half: it runs whatever test suite the
source repository already declares (by on-disk convention -- a Makefile
``test`` target, a ``package.json`` ``scripts.test``, a ``Cargo.toml``,
or a Python test layout), read-only, against the *proposed* rewritten
tree.

Never the customer's real checkout, by construction, not just by
discipline: this module's public API (``validate(request: ValidationRequest)``)
has no parameter through which a filesystem path to any pre-existing
checkout could ever be passed in -- ``ValidationRequest`` (``cairn_modules.
transformation.validation``) carries only in-memory ``SourceFile``/
``TransformationDiff`` values, never a ``Path``. This adapter's only use
of the filesystem is a single ``tempfile.TemporaryDirectory`` created
fresh inside ``validate`` and removed before it returns; every file this
adapter ever writes is written under that directory, built entirely from
``request``'s in-memory content (``request.diff.files[*].rendered_content``
where the manifest covers a file, ``request.files[*].content`` --
721's original fetch -- otherwise, so the rest of the tree a test suite
might import from is still present). ``packages/adapters/tests/
test_validation_tests.py`` has both a construction-proof check (no
filesystem path field anywhere on ``ValidationRequest``) and a behavioural
one (the created temp directory does not exist once ``validate`` returns).

No network call from this module's own code -- see the module docstring
discipline this repository already uses elsewhere (``cairn_adapters.
transform_core``'s ``no_network_imports_in_cli_source``): whatever the
*declared test command itself* does once invoked (a test suite reaching
the network) is that test suite's own business, sandboxing it is 731's
job ("731's sandbox wraps these adapters next"), not this unit's.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from cairn_modules.transformation.validation import ValidationRequest, ValidationResult

TEST_SUITE_CHECK_ID = "tests"

_TEMP_DIR_PREFIX = "cairn-validation-tests-"
_DEFAULT_TIMEOUT_SECONDS = 120
_OUTPUT_TAIL_CHARS = 2000


def _makefile_declares_test_target(makefile: Path) -> bool:
    try:
        text = makefile.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return any(line.startswith("test:") for line in text.splitlines())


def _package_json_declares_test_script(package_json: Path) -> bool:
    import json

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get("scripts", {}).get("test"))


def discover_test_command(root: Path) -> tuple[str, ...] | None:
    """The repo's own declared test command, by on-disk convention, in a
    fixed priority order. Returns ``None`` when nothing declares a test
    suite -- a legitimate "nothing to run" outcome (see ``validate``
    below), never a guessed command.
    """

    makefile = root / "Makefile"
    if makefile.is_file() and _makefile_declares_test_target(makefile):
        return ("make", "test")

    package_json = root / "package.json"
    if package_json.is_file() and _package_json_declares_test_script(package_json):
        return ("npm", "test")

    if (root / "Cargo.toml").is_file():
        return ("cargo", "test")

    has_pytest_layout = (
        (root / "pyproject.toml").is_file()
        or (root / "setup.cfg").is_file()
        or next(root.rglob("test_*.py"), None) is not None
        or next(root.rglob("*_test.py"), None) is not None
    )
    if has_pytest_layout:
        return ("python3", "-m", "pytest")

    return None


def _tail(*parts: str) -> str:
    joined = "\n".join(part for part in parts if part)
    return joined[-_OUTPUT_TAIL_CHARS:]


class TestSuiteValidationAdapter:
    """The real "tests" ``ValidationPort`` adapter.

    One check: run the repo's own declared test command (if any) against
    an isolated temp copy of the proposed rewritten tree. "No test suite
    declared" is reported as a passing result with an explanatory reason
    (there is nothing this check could have caught either way) -- it is
    never fabricated as a failure, the same "never invents a substitute"
    discipline this codebase's other adapters already use.
    """

    # Not a pytest test class, despite the name -- this is a port
    # adapter, named for the "tests" check it runs. ``__test__ = False``
    # stops pytest's default collection heuristic from warning about it.
    __test__ = False

    def __init__(self, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]:
        with tempfile.TemporaryDirectory(prefix=_TEMP_DIR_PREFIX) as tmp:
            root = Path(tmp)
            self._write_isolated_tree(root, request)
            command = discover_test_command(root)
            if command is None:
                return (
                    ValidationResult(
                        check_id=TEST_SUITE_CHECK_ID,
                        passed=True,
                        reason=(
                            "no declared test suite found in the proposed tree "
                            "(no Makefile `test` target, package.json `scripts.test`, "
                            "Cargo.toml, or pytest layout); nothing to run"
                        ),
                    ),
                )
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return (
                    ValidationResult(
                        check_id=TEST_SUITE_CHECK_ID,
                        passed=False,
                        reason=f"declared test command {command!r} failed to run: {exc}",
                    ),
                )

            passed = completed.returncode == 0
            reason = None
            if not passed:
                reason = (
                    f"declared test command {command!r} exited {completed.returncode}: "
                    f"{_tail(completed.stdout, completed.stderr)}"
                )
            return (ValidationResult(check_id=TEST_SUITE_CHECK_ID, passed=passed, reason=reason),)

    @staticmethod
    def _write_isolated_tree(root: Path, request: ValidationRequest) -> None:
        rendered_by_path = {
            file_diff.source_file_id: file_diff.rendered_content
            for file_diff in request.diff.files
        }
        for source_file in request.files:
            content = rendered_by_path.get(source_file.path, source_file.content)
            target = root / source_file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


__all__ = ["TEST_SUITE_CHECK_ID", "TestSuiteValidationAdapter", "discover_test_command"]
