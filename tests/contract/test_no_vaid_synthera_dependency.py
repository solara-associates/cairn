"""SYNTHERA is a documented boundary only; VAID is now core (ADR-020).

Unit 825 proved both names absent from this repository. ADR-020, accepted
2026-11-27, changed that for one of them: §3 adopts **VAID** for real, as
an open-source library dependency verifying a presented credential in
``cairn_kernel``. So the blanket "neither name appears anywhere" claim is
no longer true of VAID, and keeping it alive behind a growing list of
path exemptions would be asserting something false rather than proving
something true.

What this file asserts after ADR-020, therefore, is two different things
about two different systems:

1. **SYNTHERA: still absent.** The original negative proof, unchanged in
   substance, scoped to that one name. ADR-020 §4 keeps SYNTHERA exactly
   where unit 825's spec put it -- optional, commercial, behind a port
   that does not exist yet -- so "nothing in CAIRN imports or wires
   SYNTHERA" still has to hold for every file. Three independent scan
   mechanisms, so a reference cannot dodge all of them:

   a. ``ast``-parsed import statements in every ``*.py`` file;
   b. a plain-text scan of every ``pyproject.toml``/``Cargo.toml``
      (a dependency declared as a string, which ``ast`` would never see);
   c. a plain-text, case-insensitive scan over the entire tree (a stray
      network host, env var or config key an import/manifest scan misses).

2. **VAID: present, and confined to core.** ADR-020 §3 says VAID
   verification belongs in ``cairn_kernel`` -- core, not
   ``cairn_adapters`` -- because verifying a credential's own
   cryptographic structure has no provider SDK underneath it. That is now
   a structural claim worth a test of its own: the only production
   package importing the VAID library is ``cairn_kernel``, and the only
   manifest declaring it is that package's.

Paths allowed to *name* SYNTHERA, because each is required to: this test,
``docs/specs/r5-integration-boundaries.md`` (the spec documenting the
boundary), ``docs/adr/ADR-020-principal-tenant-propagation.md`` (the ADR
deciding where it would attach) and ``docs/adr/README.md`` (whose
decision-log row carries that ADR's own title). None of them implements,
imports or wires anything.

Verified as a real negative proof, not a trivial always-pass: a fake
import of the forbidden name was temporarily added to a scratch module in
this tree, this test was re-run and confirmed to fail on all applicable
checks, the line was removed, and the test was confirmed to pass again
clean. The VAID half is self-evidently not vacuous -- it fails if
``cairn_kernel`` stops importing the library at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The one name this test still proves absent (case-insensitive). VAID
#: left this tuple when ADR-020 §3 adopted it; see this module's docstring.
FORBIDDEN_NAMES: tuple[str, ...] = ("synthera",)

#: Paths allowed to mention the forbidden name (relative to REPO_ROOT),
#: because each is required to name it: this test, the spec documenting the
#: boundary, the ADR deciding where it would attach, and the ADR index
#: whose decision-log row carries that ADR's title.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "tests/contract/test_no_vaid_synthera_dependency.py",
        "docs/specs/r5-integration-boundaries.md",
        "docs/adr/ADR-020-principal-tenant-propagation.md",
        "docs/adr/README.md",
    }
)

#: The root module names the published VAID library installs as.
VAID_MODULE_ROOTS: frozenset[str] = frozenset({"vaid_mint", "vaid_pop"})

#: The one production package ADR-020 §3 puts VAID verification in.
VAID_HOME_PACKAGE = "cairn_kernel"

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


def test_no_python_import_of_synthera() -> None:
    """No ``*.py`` file imports anything whose root module name contains
    ``synthera`` (case-insensitive)."""
    violations: dict[str, set[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = _imported_roots(tree)
        hit = {root for root in roots if _contains_forbidden_name(root)}
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found an import referencing SYNTHERA, which is a documented boundary only"
        f" (see docs/specs/r5-integration-boundaries.md and ADR-020 §4): {violations}"
    )


def test_no_dependency_manifest_references_synthera() -> None:
    """No ``pyproject.toml``/``Cargo.toml`` anywhere in the repo declares a
    dependency naming SYNTHERA."""
    violations: dict[str, str] = {}
    for path in _dependency_manifests():
        text = path.read_text(encoding="utf-8")
        hit = _contains_forbidden_name(text)
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found a dependency-manifest reference to SYNTHERA, which is a documented"
        f" boundary only, not a dependency: {violations}"
    )


def test_no_repo_text_references_synthera() -> None:
    """No file in the repository, outside the four paths required to name
    it, mentions SYNTHERA, case-insensitive.

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
        "found a repo-wide text reference to SYNTHERA outside the four paths"
        f" required to name it: {violations}"
    )


@pytest.mark.parametrize("allowed_path", sorted(ALLOWED_PATHS))
def test_allowed_paths_exist(allowed_path: str) -> None:
    """Sanity check: the paths this test deliberately exempts are real
    files, not typos that would silently widen the exemption to nothing."""
    assert (REPO_ROOT / allowed_path).is_file(), f"expected {allowed_path} to exist"


# -- VAID: present, and confined to core (ADR-020 §3) -----------------


def _production_python_files() -> list[Path]:
    """Every ``*.py`` file under a package's or app's ``src/``.

    Tests are excluded deliberately: a test anywhere may import the VAID
    library to build a fixture (``cairn_kernel.testing`` exists precisely
    so they share one), and that says nothing about where the production
    dependency sits. What this test is about is the shipped import graph.
    """

    roots = [*REPO_ROOT.glob("packages/*/src"), *REPO_ROOT.glob("apps/*/src")]
    return [
        path
        for root in roots
        for path in root.rglob("*.py")
        if not _is_excluded_dir(path)
    ]


def _owning_package(path: Path) -> str:
    """The top-level Python package a ``src/`` file belongs to."""

    parts = path.relative_to(REPO_ROOT).parts
    return parts[parts.index("src") + 1]


def test_vaid_is_imported_only_from_core() -> None:
    """ADR-020 §3 puts VAID verification in ``cairn_kernel`` -- core, not
    an adapter -- because verifying a credential's own cryptographic
    structure is a kernel-level concern with no provider SDK underneath
    it. Nothing else in the shipped import graph may reach the library
    directly; everything else goes through ``cairn_kernel.vaid``.
    """

    offenders: dict[str, set[str]] = {}
    for path in _production_python_files():
        if _owning_package(path) == VAID_HOME_PACKAGE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hit = _imported_roots(tree) & VAID_MODULE_ROOTS
        if hit:
            offenders[_relative(path)] = hit
    assert not offenders, (
        "the VAID library may only be imported from cairn_kernel (ADR-020 §3: core, not"
        f" an adapter); everything else imports cairn_kernel.vaid: {offenders}"
    )


def test_vaid_is_actually_imported_by_core() -> None:
    """The positive half, so the test above cannot pass vacuously: if
    ``cairn_kernel`` stopped importing the library, VAID verification
    would be gone and this file would be asserting nothing.
    """

    importers = {
        _relative(path)
        for path in _production_python_files()
        if _owning_package(path) == VAID_HOME_PACKAGE
        and _imported_roots(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        & VAID_MODULE_ROOTS
    }
    assert importers, (
        f"expected {VAID_HOME_PACKAGE} to import the VAID library ({sorted(VAID_MODULE_ROOTS)});"
        " ADR-020 §3 adopted it, so its absence is a regression, not a clean tree"
    )


def test_only_core_declares_the_vaid_dependency() -> None:
    """One package owns the dependency, pinned, in one manifest -- so a
    second copy of it cannot drift to a different version
    (A7.supply-chain).
    """

    declaring = {
        _relative(path)
        for path in _dependency_manifests()
        if "vaid" in path.read_text(encoding="utf-8").lower()
    }
    assert declaring == {f"packages/{VAID_HOME_PACKAGE.split("_")[1]}/pyproject.toml"}, (
        "exactly one manifest may declare the VAID dependency, the one for"
        f" {VAID_HOME_PACKAGE}; found {sorted(declaring)}"
    )
