"""R3-03b: the fake/deterministic-fixture ``TransformationPort`` adapter.

Spec §5.4: ``TransformationPort | transformation | Rust core, fake``.
This is the "fake" half. It never shells out, never spawns a process,
and never touches the filesystem for a binary -- it looks up a
pre-registered raw ``CliOutput``-shaped payload per ``SourceFile`` (keyed
by the file's exact ``(path, content, language)``, the same "exact
registration, no fuzzy matching" discipline
``cairn_adapters.source_git.fake.FakeRepositorySource`` uses for its
``RepositoryRef`` fixtures) and routes it through the exact same
``cairn_modules.transformation.engine.build_manifest`` the real adapter
uses, so a drift between what the fake claims the pipeline does and what
``cairn-transform-cli`` actually does can only ever show up as a
manifest mismatch in the shared contract test
(``packages/adapters/tests/test_transform_core_contract.py``), never as
two independently-written pieces of manifest-building logic silently
disagreeing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cairn_contracts.transformation import SourceFile
from cairn_kernel.errors import NotFoundError
from cairn_modules.transformation.engine import TransformationManifest, build_manifest


def _fixture_key(source_file: SourceFile) -> tuple[str, str, str]:
    return (source_file.path, source_file.content, source_file.language.value)


class FakeTransformationPort:
    """Deterministic ``TransformationPort`` for tests.

    ``calls`` records every ``files`` sequence this adapter was asked to
    transform, in call order, so a test can assert the port was called
    with the expected files without depending on a real subprocess.
    """

    def __init__(
        self, fixtures: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None
    ) -> None:
        self._fixtures: dict[tuple[str, str, str], Mapping[str, Any]] = dict(fixtures or {})
        self.calls: list[Sequence[SourceFile]] = []

    def register(self, source_file: SourceFile, raw_cli_output: Mapping[str, Any]) -> None:
        """Register the exact raw ``CliOutput`` payload this adapter
        returns for a ``SourceFile`` with this exact path/content/
        language. ``raw_cli_output`` must be the same JSON shape the
        real ``cairn-transform-cli`` binary writes to stdout on success
        (``{"parser_version": ..., "detector_version": ..., "patcher_
        version": ..., "change_set": {...}}``) -- this adapter does not
        validate that shape itself; ``build_manifest`` is the single
        place that reads it, for both adapters alike.
        """

        self._fixtures[_fixture_key(source_file)] = raw_cli_output

    def transform(self, files: Sequence[SourceFile]) -> TransformationManifest:
        self.calls.append(files)
        cli_outputs: list[tuple[str, Mapping[str, Any]]] = []
        for source_file in files:
            key = _fixture_key(source_file)
            if key not in self._fixtures:
                raise NotFoundError(
                    f"no transform-core fixture registered for source file {source_file.path!r}"
                )
            cli_outputs.append((source_file.path, self._fixtures[key]))
        return build_manifest(cli_outputs)


__all__ = ["FakeTransformationPort"]
