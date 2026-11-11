import ast
import sys
from pathlib import Path

ESTATE_PACKAGE = Path(__file__).parents[1] / "src" / "cairn_contracts" / "estate"


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_estate_contract_files_exist() -> None:
    python_files = sorted(path.name for path in ESTATE_PACKAGE.glob("*.py"))
    assert python_files, "estate contract package must contain Python sources"


def test_estate_imports_only_stdlib_and_pydantic() -> None:
    violations: dict[str, set[str]] = {}
    for path in ESTATE_PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names
            and root not in {"pydantic", "cairn_contracts"}
        }
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"disallowed imports: {violations}"
