"""R3-01: the real ``RepositorySourcePort`` adapter for a Git ref.

Spec §5.4: ``RepositorySourcePort | transformation | Git/upload, fake``.
This is the "Git" half; ``cairn_adapters.source_git.upload_adapter`` is
the "upload" half and ``cairn_adapters.source_git.fake`` is the "fake"
half.

ADR-010 makes "no write-back" (spec §16's R3-01 row) load-bearing, not a
convenience: this module must never be able to push a commit, create or
move a branch or tag, change a remote's configuration, or otherwise
write anything back to the repository it reads. That is enforced by
construction here, not merely by discipline:

- ``_ALLOWED_GIT_SUBCOMMANDS`` is the *complete* set of git subcommands
  this module will ever invoke. ``_run_git`` refuses, before spawning a
  process, to run anything outside that set -- there is no code path
  from ``fetch`` to ``git push`` (or ``commit``, ``add``, ``remote``,
  ``config``, or any other write/configuration subcommand) because no
  call site in this file ever asks for one.
- Every clone is shallow (``--depth``) and read-only: no credential with
  write access is required or accepted, and this adapter never adds or
  mutates a remote once the clone exists.
- The clone happens in a fresh temporary directory that is removed after
  the fetch completes (or on any error) -- nothing persists on disk past
  one ``fetch`` call, and nothing is written back to ``ref.url`` itself.

``packages/adapters/tests/test_source_git.py`` has a construction-proof
test (R-ARCH-02-style, matching the discipline ``cairn_adapters.
iac_terraform`` uses for "no real Terraform binary / apply") that
statically scans this file's source for every git-subcommand string
literal passed to ``subprocess`` and asserts each one is in
``_ALLOWED_GIT_SUBCOMMANDS``, plus a runtime test that records every
subprocess call a real fetch makes and asserts the same thing dynamically.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from cairn_contracts.transformation import GitRepositoryRef, SourceFile
from cairn_kernel.errors import ProviderUnavailableError, ValidationError

from cairn_adapters.source_git.language import detect_language

# The complete, closed set of git subcommands this adapter will ever
# invoke. Every one of them is read-only against the remote: none of
# them pushes, creates/moves a ref on the remote, or changes repository
# or remote configuration.
_ALLOWED_GIT_SUBCOMMANDS = frozenset({"clone", "fetch", "checkout"})

_GIT_TIMEOUT_SECONDS = 60


def _run_git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    subcommand = args[0] if args else ""
    if subcommand not in _ALLOWED_GIT_SUBCOMMANDS:
        # Defense in depth: even a future call site that tried to pass a
        # write subcommand would be refused here before any process runs.
        raise ValidationError(
            f"source_git adapter refuses git subcommand {subcommand!r}: "
            f"not in the read-only allowlist {sorted(_ALLOWED_GIT_SUBCOMMANDS)}"
        )
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProviderUnavailableError(f"git {subcommand} failed to run: {exc}") from exc


def _checkout_ref(repo_dir: Path, ref: str) -> None:
    """Shallow-clone-then-checkout, falling back to a deeper fetch of the
    exact ref when it is not reachable from the default branch's shallow
    history (e.g. ``ref`` is a commit SHA rather than a branch/tag name).
    """
    result = _run_git(["checkout", ref], cwd=repo_dir)
    if result.returncode == 0:
        return
    fetch_result = _run_git(["fetch", "--depth", "1", "origin", ref], cwd=repo_dir)
    if fetch_result.returncode != 0:
        raise ProviderUnavailableError(
            f"could not resolve ref {ref!r}: {fetch_result.stderr.strip()}"
        )
    checkout_result = _run_git(["checkout", "FETCH_HEAD"], cwd=repo_dir)
    if checkout_result.returncode != 0:
        raise ProviderUnavailableError(
            f"could not check out ref {ref!r}: {checkout_result.stderr.strip()}"
        )


def _read_tree(repo_dir: Path) -> tuple[SourceFile, ...]:
    files: list[SourceFile] = []
    for entry in sorted(repo_dir.rglob("*")):
        if not entry.is_file():
            continue
        if ".git" in entry.relative_to(repo_dir).parts:
            continue
        relative_path = entry.relative_to(repo_dir).as_posix()
        try:
            content = entry.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file: not readable as source text. Skipped, same as
            # a file this release's languages do not claim would be --
            # the port's contract is "every readable file", not "every
            # byte on disk".
            continue
        files.append(
            SourceFile(path=relative_path, content=content, language=detect_language(relative_path))
        )
    return tuple(files)


class GitSourceAdapter:
    """The real ``RepositorySourcePort`` adapter for ``GitRepositoryRef``.

    Shallow-clones ``ref.url`` read-only into a temporary directory,
    checks out ``ref.ref``, reads every file's text content, and removes
    the temporary directory before returning -- nothing from the clone
    persists past one ``fetch`` call, and nothing is ever written back
    to ``ref.url``.
    """

    def fetch(self, ref: GitRepositoryRef) -> tuple[SourceFile, ...]:
        with tempfile.TemporaryDirectory(prefix="cairn-source-git-") as tmp:
            repo_dir = Path(tmp) / "repo"
            clone_result = _run_git(
                ["clone", "--depth", "1", "--no-single-branch", ref.url, str(repo_dir)]
            )
            if clone_result.returncode != 0:
                raise ProviderUnavailableError(
                    f"could not clone {ref.url!r}: {clone_result.stderr.strip()}"
                )
            _checkout_ref(repo_dir, ref.ref)
            files = _read_tree(repo_dir)
            # The temporary directory (including the cloned .git) is
            # removed on exit from this ``with`` block regardless of
            # outcome; explicit for clarity even though TemporaryDirectory
            # already guarantees it.
            shutil.rmtree(repo_dir, ignore_errors=True)
            return files


__all__ = ["GitSourceAdapter"]
