"""R3-01: the fake/deterministic-test ``RepositorySourcePort`` adapter.

Spec §5.4: ``RepositorySourcePort | transformation | Git/upload, fake``.
This is the "fake" half. Tests (here and in 722/723's future parser work)
register a fixed ``SourceFile`` sequence per ``RepositoryRef`` and get it
back verbatim and deterministically -- no clone, no archive unpacking, no
filesystem or process access at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from cairn_contracts.transformation import RepositoryRef, SourceFile
from cairn_kernel.errors import NotFoundError


def _ref_key(ref: RepositoryRef) -> tuple[str, str]:
    if ref.kind == "GIT":
        return ("GIT", f"{ref.url}@{ref.ref}")
    return ("UPLOAD", ref.archive_id)


class FakeRepositorySource:
    """Deterministic ``RepositorySourcePort`` for tests.

    ``fetches`` records every ``RepositoryRef`` this adapter was asked to
    fetch, in call order, so a test can assert the port was called with
    the expected ref without depending on git or the filesystem.
    """

    def __init__(self, fixtures: dict[tuple[str, str], Sequence[SourceFile]] | None = None) -> None:
        self._fixtures: dict[tuple[str, str], tuple[SourceFile, ...]] = {
            key: tuple(value) for key, value in (fixtures or {}).items()
        }
        self.fetches: list[RepositoryRef] = []

    def register(self, ref: RepositoryRef, files: Sequence[SourceFile]) -> None:
        """Register the files this adapter returns for an exact ``ref``."""
        self._fixtures[_ref_key(ref)] = tuple(files)

    def fetch(self, ref: RepositoryRef) -> Sequence[SourceFile]:
        self.fetches.append(ref)
        key = _ref_key(ref)
        if key not in self._fixtures:
            raise NotFoundError(f"no fixture registered for repository ref {key}")
        return self._fixtures[key]


__all__ = ["FakeRepositorySource"]
