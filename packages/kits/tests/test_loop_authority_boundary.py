"""R6-05: the structural half of R-AGENT-04 -- ``cairn_kits.loop`` can
reach no approval or execution authority.

The same AST-import-check shape ``packages/kernel/tests/test_model_
port.py`` uses for R-AI-02: this proves the import itself is
structurally absent from ``cairn_kits.loop``'s own source files. The
import-linter ``loop-cannot-execute`` contract (``.importlinter``)
proves the same thing at the dependency-graph level; this test proves
it one more time, directly against the source, the way R-AI-02's own
test pairs an AST check with its import-linter contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

LOOP_SRC = Path(__file__).parents[1] / "src" / "cairn_kits" / "loop"

_FORBIDDEN_IMPORT_ROOTS = {
    # Any import of cairn_modules at all is forbidden transitively --
    # kits-purity already enforces this at the package level; this test
    # re-proves it directly against the loop package's own source.
    "cairn_modules",
}


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_submodules(tree: ast.Module, root: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(root):
            modules.add(node.module)
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith(root))
    return modules


def test_loop_package_never_imports_cairn_modules() -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(LOOP_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = roots & _FORBIDDEN_IMPORT_ROOTS
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"cairn_kits.loop must not import: {violations}"


def test_loop_package_never_imports_the_execution_gate() -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(LOOP_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = _imported_submodules(tree, "cairn_kernel.execution_gate")
        if modules:
            violations[path.name] = modules
    assert not violations, f"cairn_kits.loop must not import the execution gate: {violations}"
