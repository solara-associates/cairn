"""The two integration boundaries ADR-020 settled, asserted as they now
stand: **VAID is in core, and the other system appears only behind a
port.**

Unit 825 wrote this file as a single negative proof -- neither VAID nor
the commercial policy substrate named in
``docs/specs/r5-integration-boundaries.md`` appeared anywhere in this
repository, proved by three independent repo-wide scans. ADR-020,
accepted 2026-11-27, changed what is true about both:

- **§3 adopted VAID for real**, as an open-source library verifying a
  presented credential inside ``cairn_kernel``. "VAID appears nowhere"
  stopped being true, so it is no longer asserted. What replaces it is
  the structural claim the ADR actually made: VAID verification lives in
  **core, not an adapter**, and nothing else in the shipped import graph
  reaches the library.
- **§4 gave the other system a port**: optional, commercial, behind
  ``cairn_kernel.governance``, with a no-op default so CAIRN runs fully
  without it. "Appears nowhere" is still true of that one and still
  proved below -- but on its own that is now a weaker statement than the
  ADR makes, because "nowhere" would also be satisfied by there being no
  port at all. So the negative proof is kept *and* joined by the
  positive half: the port exists, it is the only thing anything could
  attach behind, and **no adapter for it exists anywhere in this
  repository**.

What this file therefore asserts, in three groups:

1. **The commercial substrate is absent** (``test_no_*``). The original
   negative proof, unchanged in substance, scoped to that one name.
   Three independent mechanisms, so a reference cannot dodge all of them:
   ``ast``-parsed imports of every ``*.py``; a text scan of every
   ``pyproject.toml``/``Cargo.toml`` (a dependency declared as a string,
   which ``ast`` would never see); and a text scan over every tracked
   file (a stray network host, env var or config key the other two miss).
2. **VAID is present, and confined to core** (``test_vaid_*``). One
   package imports the library, one manifest declares it, and it really
   is imported -- so the confinement test cannot pass by VAID having
   quietly disappeared.
3. **The substrate could only ever attach behind the port**
   (``test_governance_*``). The port exists with the shape ADR-020 §4
   describes; the only implementation in the shipped tree is the kernel's
   own no-op default; the port's own module pulls in nothing from outside
   ``cairn_kernel`` and the standard library, so there is no import a
   vendor could hide in; and no kernel flow depends on the port, which is
   what "CAIRN works fully without it" means structurally.

Paths allowed to *name* the commercial substrate, because each is
required to: this test, the spec documenting the boundary, the ADR
deciding where it attaches, and the ADR index whose decision-log row
carries that ADR's title. None of them implements, imports or wires
anything.

Verified as real negative proofs, not trivial always-passes: a fake
import of the forbidden name was temporarily added to a scratch module
in this tree, these scans were re-run and confirmed to fail on every
applicable check, the line was removed, and they were confirmed to pass
again clean. Each positive assertion is paired with the thing that would
make it vacuous -- see ``test_vaid_is_actually_imported_by_core`` and
``test_the_governance_port_exists_with_the_shape_the_adr_describes``.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The one name this file still proves absent (case-insensitive). VAID
#: left this tuple when ADR-020 §3 adopted it; see the module docstring.
FORBIDDEN_NAMES: tuple[str, ...] = ("synthera",)

#: Paths allowed to mention the forbidden name (relative to REPO_ROOT),
#: because each is required to name it: this test, the spec documenting
#: the boundary, the ADR deciding where it attaches, and the ADR index
#: whose decision-log row carries that ADR's title.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "tests/contract/test_integration_boundaries.py",
        "docs/specs/r5-integration-boundaries.md",
        "docs/adr/ADR-020-principal-tenant-propagation.md",
        "docs/adr/README.md",
    }
)

#: The root module names the published VAID library installs as.
VAID_MODULE_ROOTS: frozenset[str] = frozenset({"vaid_mint", "vaid_pop"})

#: The one production package ADR-020 §3 puts VAID verification in.
VAID_HOME_PACKAGE = "cairn_kernel"

#: Where ADR-020 §4's port lives, and the methods it is made of.
GOVERNANCE_MODULE = "cairn_kernel.governance"
GOVERNANCE_PORT_METHODS: frozenset[str] = frozenset(
    {"check_revocation", "check_policy", "check_budget", "record"}
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
    """Every file git actually tracks.

    Asks git, rather than walking the filesystem. The claim this file
    makes is about the repository -- what a clone gets, what review sees,
    what ships -- and an untracked scratch file in someone's working
    copy is none of those. Walking the tree instead meant this scan
    disagreed with its own name and docstring, and failed locally for
    anyone with so much as an untracked note in the directory while
    being identical in CI, where a fresh checkout has nothing untracked.
    A test that only fails on developers' machines is a test people
    learn to ignore.
    """

    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    files: list[Path] = []
    for name in listed.split("\0"):
        if not name:
            continue
        path = REPO_ROOT / name
        if _is_excluded_dir(path) or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if not path.is_file():
            # A tracked path git lists but the working tree does not have
            # (a submodule gitlink, say). Nothing to scan.
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


def _production_python_files() -> list[Path]:
    """Every ``*.py`` file under a package's or app's ``src/``.

    Tests are excluded deliberately: a test anywhere may import the VAID
    library to build a fixture (``cairn_kernel.testing`` exists precisely
    so they share one) or define a governance adapter that denies, and
    neither says anything about the shipped import graph -- which is what
    these assertions are about.
    """

    roots = [*REPO_ROOT.glob("packages/*/src"), *REPO_ROOT.glob("apps/*/src")]
    return [path for root in roots for path in root.rglob("*.py") if not _is_excluded_dir(path)]


def _owning_package(path: Path) -> str:
    """The top-level Python package a ``src/`` file belongs to."""

    parts = path.relative_to(REPO_ROOT).parts
    return parts[parts.index("src") + 1]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_modules(tree: ast.Module) -> set[str]:
    """Full dotted module names, not just roots -- needed to tell
    ``cairn_kernel.governance`` from the rest of ``cairn_kernel``."""

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _contains_forbidden_name(text: str) -> str | None:
    lowered = text.lower()
    for name in FORBIDDEN_NAMES:
        if name in lowered:
            return name
    return None


# -- 1. the commercial substrate is absent -----------------------------


def test_no_python_import_of_the_commercial_substrate() -> None:
    """No ``*.py`` file imports anything whose root module name contains
    the forbidden name (case-insensitive)."""

    violations: dict[str, set[str]] = {}
    for path in _python_files():
        hit = {root for root in _imported_roots(_parse(path)) if _contains_forbidden_name(root)}
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found an import referencing the commercial policy substrate, which is a documented"
        " boundary only (docs/specs/r5-integration-boundaries.md and ADR-020 §4):"
        f" {violations}"
    )


def test_no_dependency_manifest_references_the_commercial_substrate() -> None:
    """No ``pyproject.toml``/``Cargo.toml`` anywhere declares a dependency
    naming it."""

    violations: dict[str, str] = {}
    for path in _dependency_manifests():
        hit = _contains_forbidden_name(path.read_text(encoding="utf-8"))
        if hit:
            violations[_relative(path)] = hit
    assert not violations, (
        "found a dependency-manifest reference to the commercial policy substrate, which is"
        f" a documented boundary only, not a dependency: {violations}"
    )


def test_no_tracked_file_references_the_commercial_substrate() -> None:
    """No file git tracks, outside the four paths required to name it,
    mentions it -- case-insensitive.

    The broadest of the three: it also catches a network host string, an
    environment variable name or a config key that an import or manifest
    scan alone would not see.
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
        "found a tracked-file text reference to the commercial policy substrate outside the"
        f" four paths required to name it: {violations}"
    )


@pytest.mark.parametrize("allowed_path", sorted(ALLOWED_PATHS))
def test_allowed_paths_exist(allowed_path: str) -> None:
    """Sanity check: the paths this file deliberately exempts are real
    files, not typos that would silently widen the exemption to
    nothing."""

    assert (REPO_ROOT / allowed_path).is_file(), f"expected {allowed_path} to exist"


# -- 2. VAID is present, and confined to core (ADR-020 §3) -------------


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
        hit = _imported_roots(_parse(path)) & VAID_MODULE_ROOTS
        if hit:
            offenders[_relative(path)] = hit
    assert not offenders, (
        "the VAID library may only be imported from cairn_kernel (ADR-020 §3: core, not an"
        f" adapter); everything else imports cairn_kernel.vaid: {offenders}"
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
        and _imported_roots(_parse(path)) & VAID_MODULE_ROOTS
    }
    assert importers, (
        f"expected {VAID_HOME_PACKAGE} to import the VAID library"
        f" ({sorted(VAID_MODULE_ROOTS)}); ADR-020 §3 adopted it, so its absence is a"
        " regression, not a clean tree"
    )


def test_only_core_declares_the_vaid_dependency() -> None:
    """One package owns the dependency, pinned, in one manifest -- so a
    second copy cannot drift to a different version (A7.supply-chain).
    """

    declaring = {
        _relative(path)
        for path in _dependency_manifests()
        if "vaid" in path.read_text(encoding="utf-8").lower()
    }
    assert declaring == {"packages/kernel/pyproject.toml"}, (
        "exactly one manifest may declare the VAID dependency, the one for"
        f" {VAID_HOME_PACKAGE}; found {sorted(declaring)}"
    )


def test_the_vaid_dependency_is_pinned_to_one_minor() -> None:
    """PyPI has no caret convention, so an open ``>=`` would resolve onto
    the next breaking release without telling anyone (A7.supply-chain).
    """

    manifest = (REPO_ROOT / "packages/kernel/pyproject.toml").read_text(encoding="utf-8")
    pins = [
        stripped
        for line in manifest.splitlines()
        # Comments in that file explain the pin and name the package too.
        if "vaid-mint" in (stripped := line.strip()) and not stripped.startswith("#")
    ]
    assert pins, "expected packages/kernel/pyproject.toml to declare vaid-mint"
    for pin in pins:
        assert "<" in pin, f"the VAID dependency must carry an upper bound; found {pin!r}"


# -- 3. the substrate could only attach behind the port (ADR-020 §4) ---


def test_the_governance_port_exists_with_the_shape_the_adr_describes() -> None:
    """The positive half of "appears only behind the port": without a
    port, "nowhere" would be satisfied by there being nothing to attach
    behind, and this file would be proving far less than ADR-020 §4
    decided.

    Imported here rather than scanned, because what matters is the shape
    a real adapter would have to satisfy -- the four concerns the ADR
    names, plus a default that allows everything.
    """

    from cairn_kernel.governance import GovernancePort, NoOpGovernance

    missing = GOVERNANCE_PORT_METHODS - set(dir(GovernancePort))
    assert not missing, f"the governance port is missing ADR-020 §4's concerns: {sorted(missing)}"
    assert not GOVERNANCE_PORT_METHODS - set(dir(NoOpGovernance)), (
        "the default adapter must implement the whole port"
    )


def test_the_only_governance_adapter_in_the_shipped_tree_is_the_no_op_default() -> None:
    """ "Behind the port" with nothing behind it yet: no adapter for the
    commercial substrate exists in this repository, so the only thing
    satisfying the port's shape is the kernel's own no-op.

    Structural rather than nominal -- any class defining all four of the
    port's methods counts, whether or not it says it implements the
    port -- so an adapter could not land under another name and go
    unnoticed.
    """

    implementations: dict[str, list[str]] = {}
    for path in _production_python_files():
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            if GOVERNANCE_PORT_METHODS <= methods:
                implementations.setdefault(_relative(path), []).append(node.name)
    assert implementations == {
        "packages/kernel/src/cairn_kernel/governance/ports.py": ["GovernancePort", "NoOpGovernance"]
    }, (
        "the only implementations of the governance port in the shipped tree must be the port"
        f" itself and its no-op default (ADR-020 §4: no adapter is built here); found"
        f" {implementations}"
    )


def test_the_governance_port_imports_nothing_from_outside_core() -> None:
    """There is no import here a vendor could ever appear in.

    The port is a shape, not an integration: it defines itself out of
    ``cairn_kernel`` and the standard library alone. That is what keeps
    ADR-020 §4's "never inside ``cairn_kernel``" true of the *adapter*
    while the *port* lives there.
    """

    module_dir = REPO_ROOT / "packages/kernel/src/cairn_kernel/governance"
    third_party: dict[str, set[str]] = {}
    for path in sorted(module_dir.rglob("*.py")):
        external = {
            root
            for root in _imported_roots(_parse(path))
            if root not in {"cairn_kernel"} and root not in _STDLIB_ROOTS
        }
        if external:
            third_party[_relative(path)] = external
    assert not third_party, (
        f"the governance port must import only cairn_kernel and the standard library;"
        f" found {third_party}"
    )


def test_no_kernel_flow_depends_on_the_governance_port() -> None:
    """What "CAIRN works fully without it" (ADR-020 §4) means
    structurally: the port is called from above -- the MCP gateway and
    the agent loop -- and no kernel module reaches for it, so no core
    flow needs an adapter bound to work.
    """

    dependents = {
        _relative(path)
        for path in _production_python_files()
        if _owning_package(path) == VAID_HOME_PACKAGE
        and not _relative(path).startswith("packages/kernel/src/cairn_kernel/governance/")
        and any(
            module == GOVERNANCE_MODULE or module.startswith(f"{GOVERNANCE_MODULE}.")
            for module in _imported_modules(_parse(path))
        )
    }
    assert not dependents, (
        "no cairn_kernel flow may depend on the governance port -- CAIRN works fully with no"
        f" adapter bound (ADR-020 §4); found {sorted(dependents)}"
    )


#: Standard-library roots the governance port legitimately uses. An
#: explicit list rather than ``sys.stdlib_module_names`` so that adding
#: an import to that module is a deliberate edit here too.
_STDLIB_ROOTS: frozenset[str] = frozenset(
    {"__future__", "abc", "collections", "dataclasses", "enum", "typing"}
)
