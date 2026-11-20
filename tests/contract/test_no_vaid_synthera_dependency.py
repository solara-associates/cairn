"""Unit 825 negative proof: VAID and SYNTHERA are documented boundaries
only (``docs/specs/r5-integration-boundaries.md``), never implemented.

This test asserts that no actual import, package dependency, or network
host/string reference to either name exists anywhere in this repository
today. It is intentionally repo-wide (not scoped to one package) because
the claim it proves is repo-wide: "nothing in CAIRN talks to VAID or
SYNTHERA" has to hold for every file, not just the MCP/A2A gateway that the
spec names as the hypothetical attach point.

Three independent scan mechanisms, so a reference can't dodge all of them:

1. ``ast``-parsed import statements in every ``*.py`` file (catches a real
   ``import vaid_sdk`` or ``from synthera import ...``).
2. A plain-text scan of every ``pyproject.toml``/``Cargo.toml`` dependency
   manifest (catches a dependency declared as a string, which ``ast`` over
   Python source would never see).
3. A plain-text, case-insensitive scan over the *entire* tracked tree
   (catches a stray network host string, env var, or config key naming
   either system, which an import/manifest scan alone would miss).

Excluded from all three: this test file itself (whose own source
necessarily contains the strings it looks for) and
``docs/specs/r5-integration-boundaries.md`` (the one place in the repo that
is *required* to name them, since it documents the boundary). Everything
else in the repository, tests included, must stay clean.

Verified as a real negative proof, not a trivial always-pass: a fake
``import vaid_client`` line was temporarily added to a scratch module in
this tree, this test was re-run and confirmed to fail on all applicable
checks, the line was removed, and the test was confirmed to pass again
clean. See the unit's PR description for that verification run.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Names this test proves are absent from the codebase (case-insensitive).
FORBIDDEN_NAMES: tuple[str, ...] = ("vaid", "synthera")

#: Paths allowed to mention the names (relative to REPO_ROOT), because they
#: are the test and the spec documenting the boundary itself.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "tests/contract/test_no_vaid_synthera_dependency.py",
        "docs/specs/r5-integration-boundaries.md",
    }
)

#: Directories never scanned: VCS internals and build/dependency caches
#: that are not part of the tracked source tree.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "target",
        "dist",
        "build",
        ".uv-cache",
    }
)

#: Binary-ish or generated extensions not worth text-scanning.
EXCLUDED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".lock",
        ".svg",
    }
)


def _is_excluded_dir(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _is_allowed(path: Path) -> bool:
    return _relative(path) in ALLOWED_PATHS


def _iter_tracked_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if path.is_dir():
            continue
        if _is_excluded_dir(path):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def _python_files() -> list[Path]:
    return [
        path
        for path in REPO_ROOT.rglob("*.py")
        if not _is_excluded_dir(path) and not _is_allowed(path)
    ]


def _dependency_manifests() -> list[Path]:
    manifests: list[Path] = []
    for pattern in ("pyproject.toml", "Cargo.toml"):
        manifests.extend(path for path in REPO_ROOT.rglob(pattern) if not _is_excluded_dir(path))
    return manifests


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _contains_forbidden_name(text: str) -> str | None:
    lowered = text.lower()
    for name in FORBIDDEN_NAMES:
        if name in lowered:
            return name
    return None


def test_no_python_import_of_vaid_or_synthera() -> None:
    """No ``*.py`` file imports anything whose root module name contains
    ``vaid`` or ``synthera`` (case-insensitive)."""
    violations: dict[str, set[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = _imported_roots(tree)
        hit = {root for root in roots if _contains_forbidden_name(root)}
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found an import referencing a forbidden name (VAID/SYNTHERA are a"
        f" documented boundary only, see docs/specs/r5-integration-boundaries.md): {violations}"
    )


def test_no_dependency_manifest_references_vaid_or_synthera() -> None:
    """No ``pyproject.toml``/``Cargo.toml`` anywhere in the repo declares a
    dependency naming VAID or SYNTHERA."""
    violations: dict[str, str] = {}
    for path in _dependency_manifests():
        text = path.read_text(encoding="utf-8")
        hit = _contains_forbidden_name(text)
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found a dependency-manifest reference to a forbidden name (VAID/SYNTHERA"
        f" are a documented boundary only, not a dependency): {violations}"
    )


def test_no_repo_text_references_vaid_or_synthera() -> None:
    """No tracked file in the repository (outside the test and the spec
    that documents the boundary) mentions VAID or SYNTHERA, case-insensitive.

    This is the broadest of the three checks: it also catches a network
    host string, an environment variable name, or a config key that an
    import or manifest scan alone would not see.
    """
    violations: dict[str, str] = {}
    for path in _iter_tracked_files():
        if _is_allowed(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            # Not a text file we can meaningfully scan; binary files are
            # excluded by extension above, this is a defensive fallback.
            continue
        hit = _contains_forbidden_name(text)
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found a repo-wide text reference to a forbidden name outside the"
        f" documented boundary spec and this test: {violations}"
    )


@pytest.mark.parametrize("allowed_path", sorted(ALLOWED_PATHS))
def test_allowed_paths_exist(allowed_path: str) -> None:
    """Sanity check: the two paths this test deliberately exempts are real
    files, not typos that would silently widen the exemption to nothing."""
    assert (REPO_ROOT / allowed_path).is_file(), f"expected {allowed_path} to exist"
