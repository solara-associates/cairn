"""R3-05: the real static ``ValidationPort`` adapter.

Spec §5.4: ``ValidationPort | transformation | test/static runner, fake``.
This is the "static runner" half, wrapping 729's new Rust
``cairn-transform-validator-cli`` the same way ``cairn_adapters.
transform_core.subprocess_adapter.SubprocessTransformationPort`` already
wraps 726's ``cairn-transform-cli`` -- one subprocess invocation per source
file, fed that file's original text, language, and proposed edits
(flattened out of 726's ``TransformationManifest``) on stdin, and expected
to write ``{"results": [...]}`` JSON (or ``{"error": ...}``) to stdout.

No credential, no cloud command, no network call anywhere on this
boundary: the subprocess this adapter spawns is always the local
``cairn-transform-validator-cli`` binary (never a shell, never a
user-supplied command), fed one file's text and proposed edits on stdin
and nothing else. ``packages/adapters/tests/test_validation_static.py``
has a construction-proof test that statically scans this file for a
shell-enabled subprocess call or a networking-module import and asserts
neither appears.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from cairn_kernel.errors import ProviderUnavailableError
from cairn_modules.transformation.engine import ManifestOutcome
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult

_VALIDATOR_CLI_BIN_ENV = "CAIRN_TRANSFORM_VALIDATOR_CLI_BIN"
_DEFAULT_TIMEOUT_SECONDS = 30


class ValidatorCliUnavailableError(ProviderUnavailableError):
    """Raised when ``cairn-transform-validator-cli`` cannot be found,
    cannot be run, times out, or exits non-zero / writes a payload this
    adapter cannot parse. Always raised, never swallowed -- this adapter
    never substitutes a guessed/invented result for a check it could not
    actually run (the same "never invents a substitute" discipline
    ``TransformCliUnavailableError`` already uses for 726's binary)."""


def _candidate_binary_paths() -> tuple[Path, ...]:
    """Mirrors ``cairn_adapters.transform_core.subprocess_adapter.
    _candidate_binary_paths`` exactly -- same repo-root resolution, same
    release-before-debug ordering, same reasoning (CI builds release;
    debug is the local-dev fallback after a plain ``cargo build``)."""

    repo_root = Path(__file__).resolve().parents[5]
    return (
        repo_root / "target" / "release" / "cairn-transform-validator-cli",
        repo_root / "target" / "debug" / "cairn-transform-validator-cli",
    )


def resolve_validator_cli_binary() -> Path:
    """The exact binary this adapter will invoke. Raises
    ``ValidatorCliUnavailableError`` rather than guessing or falling back
    to a different mechanism if none can be found."""

    override = os.environ.get(_VALIDATOR_CLI_BIN_ENV)
    if override:
        path = Path(override)
        if not path.is_file():
            raise ValidatorCliUnavailableError(
                f"{_VALIDATOR_CLI_BIN_ENV}={override!r} does not point to a file"
            )
        return path

    for candidate in _candidate_binary_paths():
        if candidate.is_file():
            return candidate

    raise ValidatorCliUnavailableError(
        "cairn-transform-validator-cli binary not found; set "
        f"{_VALIDATOR_CLI_BIN_ENV} or run "
        "`cargo build -p cairn-transform-validator` first"
    )


class StaticValidationAdapter:
    """The real static-check ``ValidationPort`` adapter: one
    ``cairn-transform-validator-cli`` subprocess invocation per source file
    the manifest covers, each fed that file's original content, language,
    and every ``APPLIED`` entry's edits -- never a ``SKIPPED``/
    ``UNSUPPORTED`` entry's edits, which are always empty anyway (the same
    invariant ``cairn_modules.transformation.diff._apply_edits`` already
    relies on).
    """

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._binary_path = binary_path or resolve_validator_cli_binary()
        self._timeout_seconds = timeout_seconds

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]:
        files_by_path = {source_file.path: source_file for source_file in request.files}
        results: list[ValidationResult] = []
        for source_file_id in request.manifest.source_file_ids:
            source_file = files_by_path[source_file_id]
            entries = [
                entry
                for entry in request.manifest.entries
                if entry.source_file_id == source_file_id
            ]
            edits = [
                edit
                for entry in entries
                if entry.outcome is ManifestOutcome.APPLIED
                for edit in entry.edits
            ]
            results.extend(self._run_one(source_file, edits))
        return tuple(results)

    def _run_one(self, source_file, edits: list) -> list[ValidationResult]:
        payload = json.dumps(
            {
                "source_file_id": source_file.path,
                "language": source_file.language.value,
                "source_text": source_file.content,
                "edits": [
                    {
                        "span": {
                            "start_byte": edit.start_byte,
                            "end_byte": edit.end_byte,
                            "start_line": edit.start_line,
                            "end_line": edit.end_line,
                        },
                        "replacement": edit.replacement,
                    }
                    for edit in edits
                ],
            }
        )
        try:
            completed = subprocess.run(
                [str(self._binary_path)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidatorCliUnavailableError(
                f"cairn-transform-validator-cli failed to run for {source_file.path!r}: {exc}"
            ) from exc

        try:
            raw_output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValidatorCliUnavailableError(
                f"cairn-transform-validator-cli produced invalid JSON for "
                f"{source_file.path!r}: {completed.stdout!r}"
            ) from exc

        if completed.returncode != 0 or not isinstance(raw_output, dict) or "results" not in raw_output:
            message = (
                raw_output.get("error", "unknown error")
                if isinstance(raw_output, dict)
                else raw_output
            )
            raise ValidatorCliUnavailableError(
                f"cairn-transform-validator-cli failed for {source_file.path!r}: {message}"
            )

        return [
            ValidationResult(
                check_id=f"{source_file.path}:{raw_result['check_id']}",
                passed=raw_result["passed"],
                reason=raw_result.get("reason"),
            )
            for raw_result in raw_output["results"]
        ]


__all__ = [
    "StaticValidationAdapter",
    "ValidatorCliUnavailableError",
    "resolve_validator_cli_binary",
]
