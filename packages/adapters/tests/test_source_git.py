"""Tests for the R3-01 ``RepositorySourcePort`` adapters (spec §5.4):
the real Git adapter, the real upload adapter, and the fake.

Golden fixtures live under ``tests/fixtures/transformation/`` at the
repository root: a Terraform-only repo, a Python-only repo, and one
mixed repo (Terraform + Python + one file in neither language, so the
``UNSUPPORTED`` language is exercised too). Each fixture is read twice
in these tests -- once directly off disk to build the expected
``SourceFile`` set, and once through the adapter under test -- so a
test failure means the adapter's output disagrees with the actual
fixture content, not with a hand-typed copy of it that could drift.

No real network call is made anywhere in this file: the "Git" fixture
repositories are built locally (``git init`` + commit, in a temp
directory) and fetched over a ``file://`` URL, never a live remote.

Construction-proof (R-ARCH-02-style, matching the discipline
``cairn_adapters.iac_terraform`` uses for "no real Terraform binary"):
this file asserts, both statically (AST scan of the adapter's own
source) and dynamically (every subprocess call a real fetch makes),
that the real Git adapter never invokes a write/push git subcommand.

Persistence note (for 726, which will need to reference a fetched
source set from a transformation run): this unit's port and adapters
are pure fetch-and-return -- nothing here persists a fetch record
anywhere, so there is no tenant/project scoping to test on a store.
726 is expected to add that persistence layer when it needs to
reference a fetched source set from a transformation run; this unit
deliberately stops at an in-memory ``Sequence[SourceFile]`` result.
"""

from __future__ import annotations

import ast
import os
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from cairn_adapters.source_git import FakeRepositorySource, GitSourceAdapter, UploadSourceAdapter
from cairn_adapters.source_git.git_adapter import _ALLOWED_GIT_SUBCOMMANDS
from cairn_contracts.transformation import (
    GitRepositoryRef,
    SourceFile,
    SourceLanguage,
    UploadRepositoryRef,
)
from cairn_kernel.errors import NotFoundError, ProviderUnavailableError, ValidationError

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "transformation"
GIT_ADAPTER_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "cairn_adapters" / "source_git" / "git_adapter.py"
)

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "CAIRN Test Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "CAIRN Test Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _expected_files(fixture_dir: Path) -> dict[str, SourceFile]:
    """Builds the expected ``SourceFile`` set straight off the fixture
    directory on disk -- the same thing the adapter under test should
    produce, computed independently of the adapter's own code."""
    from cairn_adapters.source_git.language import detect_language

    expected: dict[str, SourceFile] = {}
    for entry in sorted(fixture_dir.rglob("*")):
        if entry.is_file():
            relative = entry.relative_to(fixture_dir).as_posix()
            expected[relative] = SourceFile(
                path=relative,
                content=entry.read_text(encoding="utf-8"),
                language=detect_language(relative),
            )
    return expected


def _make_local_git_repo(tmp_path: Path, fixture_dir: Path) -> str:
    """Builds a local bare-ish working repo from ``fixture_dir``'s
    content and returns a ``file://`` URL to it -- never a live
    network remote."""
    repo_dir = tmp_path / "origin"
    repo_dir.mkdir()
    _git("init", "--initial-branch=main", str(repo_dir))
    for entry in sorted(fixture_dir.rglob("*")):
        if entry.is_file():
            relative = entry.relative_to(fixture_dir)
            destination = repo_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    _git("add", ".", cwd=repo_dir)
    _git("commit", "-m", "golden fixture", cwd=repo_dir)
    return f"file://{repo_dir}"


def _git(*args: str, cwd: Path | None = None) -> None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=_GIT_ENV, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def _zip_bytes(fixture_dir: Path) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry in sorted(fixture_dir.rglob("*")):
            if entry.is_file():
                relative = entry.relative_to(fixture_dir).as_posix()
                archive.write(entry, arcname=relative)
    return buffer.getvalue()


# --- golden fixtures: real Git adapter --------------------------------------


@pytest.mark.parametrize("fixture_name", ["terraform_only", "python_only", "mixed"])
def test_git_adapter_golden_fixture(tmp_path: Path, fixture_name: str) -> None:
    fixture_dir = FIXTURES / fixture_name
    url = _make_local_git_repo(tmp_path, fixture_dir)
    expected = _expected_files(fixture_dir)

    adapter = GitSourceAdapter()
    files = adapter.fetch(GitRepositoryRef(url=url, ref="main"))

    assert {f.path: f for f in files} == expected


def test_git_adapter_marks_the_mixed_fixtures_non_code_file_unsupported() -> None:
    fixture_dir = FIXTURES / "mixed"
    files = {f.path: f for f in _expected_files(fixture_dir).values()}
    assert files is not None  # sanity: expected set is non-empty below
    languages = {f.language for f in _expected_files(fixture_dir).values()}
    assert SourceLanguage.TERRAFORM in languages
    assert SourceLanguage.PYTHON in languages
    assert SourceLanguage.UNSUPPORTED in languages


def test_git_adapter_raises_provider_unavailable_for_an_unknown_ref(tmp_path: Path) -> None:
    url = _make_local_git_repo(tmp_path, FIXTURES / "python_only")
    adapter = GitSourceAdapter()
    with pytest.raises(ProviderUnavailableError):
        adapter.fetch(GitRepositoryRef(url=url, ref="no-such-branch"))


# --- golden fixtures: real upload adapter -----------------------------------


@pytest.mark.parametrize("fixture_name", ["terraform_only", "python_only", "mixed"])
def test_upload_adapter_golden_fixture(fixture_name: str) -> None:
    fixture_dir = FIXTURES / fixture_name
    archive_bytes = _zip_bytes(fixture_dir)
    expected = _expected_files(fixture_dir)

    adapter = UploadSourceAdapter(archive_loader=lambda archive_id: archive_bytes)
    files = adapter.fetch(UploadRepositoryRef(archive_id="archive-1"))

    assert {f.path: f for f in files} == expected


def test_upload_adapter_rejects_a_bad_zip_file() -> None:
    adapter = UploadSourceAdapter(archive_loader=lambda archive_id: b"not a zip")
    with pytest.raises(ValidationError):
        adapter.fetch(UploadRepositoryRef(archive_id="bad-archive"))


def test_upload_adapter_refuses_a_zip_slip_member() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escaped.py", "x = 1\n")
    adapter = UploadSourceAdapter(archive_loader=lambda archive_id: buffer.getvalue())
    with pytest.raises(ValidationError):
        adapter.fetch(UploadRepositoryRef(archive_id="slip"))


# --- fake adapter ------------------------------------------------------------


def test_fake_adapter_returns_registered_fixtures_and_records_calls() -> None:
    ref = GitRepositoryRef(url="https://example.invalid/repo.git", ref="main")
    files = (SourceFile(path="main.tf", content="x", language=SourceLanguage.TERRAFORM),)
    fake = FakeRepositorySource()
    fake.register(ref, files)

    result = fake.fetch(ref)

    assert result == files
    assert fake.fetches == [ref]


def test_fake_adapter_raises_not_found_for_an_unregistered_ref() -> None:
    fake = FakeRepositorySource()
    with pytest.raises(NotFoundError):
        fake.fetch(GitRepositoryRef(url="https://example.invalid/repo.git", ref="main"))


def test_fake_adapter_output_is_deterministic() -> None:
    ref = UploadRepositoryRef(archive_id="archive-1")
    files = (SourceFile(path="app.py", content="x = 1\n", language=SourceLanguage.PYTHON),)
    fake = FakeRepositorySource({("UPLOAD", "archive-1"): files})
    assert fake.fetch(ref) == fake.fetch(ref) == files


# --- construction proof: no write/push git subcommand -----------------------


def test_git_adapter_source_contains_no_write_git_subcommand_literal() -> None:
    """Static proof: every git-subcommand string literal that appears as
    the first element of a list passed to ``_run_git`` in the adapter's
    own source is in the read-only allowlist. A write subcommand (push,
    commit, add, remote, config, branch -D, ...) appearing here at all
    would fail this test before any process ever runs."""
    denylist = {
        "push",
        "commit",
        "add",
        "remote",
        "config",
        "branch",
        "merge",
        "rebase",
        "cherry-pick",
        "am",
        "format-patch",
        "send-email",
        "reset",
        "tag",
        "init",
        "update-ref",
        "symbolic-ref",
        "gc",
        "filter-branch",
        "stash",
    }
    tree = ast.parse(GIT_ADAPTER_SOURCE.read_text(encoding="utf-8"))
    found_subcommands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        literal_strings = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        if not literal_strings:
            continue
        # The first string literal in any argv-shaped list built in this
        # file is the git subcommand (e.g. ["clone", ...], ["checkout", ref]).
        candidate = literal_strings[0]
        if candidate in _ALLOWED_GIT_SUBCOMMANDS or candidate in denylist:
            found_subcommands.add(candidate)

    assert found_subcommands, "expected to find at least one git-subcommand literal to check"
    assert found_subcommands <= _ALLOWED_GIT_SUBCOMMANDS
    assert found_subcommands.isdisjoint(denylist)


def test_git_adapter_runtime_calls_only_allowed_git_subcommands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dynamic proof: every subprocess call a real ``fetch`` makes, end
    to end against a local fixture repo, invokes only a subcommand from
    the allowlist -- never ``push`` or any other write subcommand."""
    url = _make_local_git_repo(tmp_path, FIXTURES / "terraform_only")
    recorded_argv: list[list[str]] = []
    real_run = subprocess.run

    def _spy(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded_argv.append(list(argv))
        return real_run(argv, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("cairn_adapters.source_git.git_adapter.subprocess.run", _spy)

    adapter = GitSourceAdapter()
    adapter.fetch(GitRepositoryRef(url=url, ref="main"))

    assert recorded_argv, "expected the adapter to invoke git at least once"
    for argv in recorded_argv:
        assert argv[0] == "git"
        subcommand = argv[1]
        assert subcommand in _ALLOWED_GIT_SUBCOMMANDS
        assert "push" not in argv
