"""R3-03b: the real ``TransformationPort`` adapter.

Spec §5.4: ``TransformationPort | transformation | Rust core, fake``.
Resolves per this plan's §7 open-question 1 (``~/solara/lz2026/
cairn-r3-briefs.md``): a subprocess boundary over 722's versioned JSON
contract, not an in-process FFI extension -- simpler to sandbox (a later
unit, 731) and keeps the Rust/Python dependency arrow one-directional
(ADR-006). This module never imports any Rust-generated binding; it only
spawns a fixed, pinned binary (``cairn-transform-cli``, 726's new thin
Rust CLI crate chaining 722/723's parsers, 724's detector and 725's
patcher end to end) and speaks JSON over its stdin/stdout.

No credential, no cloud command, no network call anywhere on this
boundary: the subprocess this adapter spawns is always the local
``cairn-transform-cli`` binary (never a shell, never a user-supplied
command), fed one file's source text on stdin and nothing else, and
``cairn-transform-cli`` itself only ever reads stdin / writes stdout
(see that crate's own ``no_network_imports_in_cli_source`` test). This
module's own construction-proof test
(``packages/adapters/tests/test_transform_core_subprocess.py::
test_subprocess_call_never_uses_a_shell_or_network_module``) statically
scans this file for ``shell=True`` and any ``socket``/``http``/``urllib``
import and asserts neither appears.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from cairn_contracts.mapping import MappingRelease
from cairn_contracts.transformation import SourceFile, SourceLanguage
from cairn_kernel.errors import ProviderUnavailableError
from cairn_modules.transformation.engine import TransformationManifest, build_manifest

_TRANSFORM_CLI_BIN_ENV = "CAIRN_TRANSFORM_CLI_BIN"
_DEFAULT_TIMEOUT_SECONDS = 30


class TransformCliUnavailableError(ProviderUnavailableError):
    """Raised when the ``cairn-transform-cli`` binary cannot be found,
    cannot be run, times out, or exits non-zero / writes a payload this
    adapter cannot parse as the ``CliOutput`` contract. Always raised,
    never swallowed -- this adapter never substitutes a guessed manifest
    for a run it could not actually complete (ADR-004's "never invents a
    substitute" discipline, applied here to the transform pipeline
    itself rather than a mapping lookup)."""


def _candidate_binary_paths() -> tuple[Path, ...]:
    """Where this adapter looks for the compiled binary, in order, when
    ``CAIRN_TRANSFORM_CLI_BIN`` is not set. Both candidates are relative
    to this repository's Cargo workspace root (four directories up from
    this file: ``packages/adapters/src/cairn_adapters/transform_core/``
    -> repo root), matching where ``cargo build`` places binaries by
    default. Release is checked first because CI builds it in release
    mode (faster pipeline, and the one actually exercised by the real
    integration test); debug is the local-dev fallback after a plain
    ``cargo build``.
    """

    repo_root = Path(__file__).resolve().parents[5]
    return (
        repo_root / "target" / "release" / "cairn-transform-cli",
        repo_root / "target" / "debug" / "cairn-transform-cli",
    )


def resolve_transform_cli_binary() -> Path:
    """The exact binary this adapter will invoke. Raises
    ``TransformCliUnavailableError`` rather than guessing or falling back
    to a different mechanism if none can be found -- a missing binary is
    a configuration/build problem to surface honestly, not something to
    paper over.
    """

    override = os.environ.get(_TRANSFORM_CLI_BIN_ENV)
    if override:
        path = Path(override)
        if not path.is_file():
            raise TransformCliUnavailableError(
                f"{_TRANSFORM_CLI_BIN_ENV}={override!r} does not point to a file"
            )
        return path

    for candidate in _candidate_binary_paths():
        if candidate.is_file():
            return candidate

    raise TransformCliUnavailableError(
        "cairn-transform-cli binary not found; set "
        f"{_TRANSFORM_CLI_BIN_ENV} or run `cargo build -p cairn-transform-cli` first"
    )


def _parse_input_payload(source_file: SourceFile) -> str:
    return json.dumps(
        {
            "source_file_id": source_file.path,
            "language": source_file.language.value,
            "source_text": source_file.content,
        }
    )


class SubprocessTransformationPort:
    """The real ``TransformationPort`` adapter: one ``cairn-transform-cli``
    subprocess invocation per ``SourceFile``, each fed exactly that
    file's ``ParseInput`` JSON on stdin and expected to write exactly one
    ``CliOutput`` JSON object (or a ``{"error": ...}`` payload) to
    stdout. A file with ``language == UNSUPPORTED`` (ADR-015's R3 scope)
    is never sent to the subprocess at all -- it is simply absent from
    the resulting manifest, the same "readable but out of scope, never
    silently coerced" treatment 721's ``SourceFile.language`` already
    gives it.
    """

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        mapping_release: MappingRelease | None = None,
    ) -> None:
        self._binary_path = binary_path or resolve_transform_cli_binary()
        self._timeout_seconds = timeout_seconds
        # Unit 780 (R4-01): threaded straight through to ``build_manifest``,
        # which is the only place that actually calls 700/R2-01's resolver.
        # Omitting it (the default) is legal, and is itself the honest
        # "no mapping release available" path for any rule that needs one.
        self._mapping_release = mapping_release

    def transform(self, files: Sequence[SourceFile]) -> TransformationManifest:
        cli_outputs: list[tuple[str, dict]] = []
        for source_file in files:
            if source_file.language is SourceLanguage.UNSUPPORTED:
                continue
            raw_output = self._run_one(source_file)
            cli_outputs.append((source_file.path, raw_output))
        return build_manifest(cli_outputs, mapping_release=self._mapping_release)

    def _run_one(self, source_file: SourceFile) -> dict:
        payload = _parse_input_payload(source_file)
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
            raise TransformCliUnavailableError(
                f"cairn-transform-cli failed to run for {source_file.path!r}: {exc}"
            ) from exc

        try:
            raw_output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise TransformCliUnavailableError(
                f"cairn-transform-cli produced invalid JSON for {source_file.path!r}: "
                f"{completed.stdout!r}"
            ) from exc

        if completed.returncode != 0 or "error" in raw_output:
            message = raw_output.get("error", "unknown error") if isinstance(raw_output, dict) else raw_output
            raise TransformCliUnavailableError(
                f"cairn-transform-cli failed for {source_file.path!r}: {message}"
            )

        if not isinstance(raw_output, dict) or "change_set" not in raw_output:
            raise TransformCliUnavailableError(
                f"cairn-transform-cli produced an unrecognized payload for "
                f"{source_file.path!r}: {raw_output!r}"
            )

        return raw_output


__all__ = [
    "SubprocessTransformationPort",
    "TransformCliUnavailableError",
    "resolve_transform_cli_binary",
]
