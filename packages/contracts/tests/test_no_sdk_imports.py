import ast
import sys
from pathlib import Path

import pytest

CONTRACTS_SRC = Path(__file__).parents[1] / "src" / "cairn_contracts"

CONTRACT_PACKAGES = ["estate", "events", "api"]


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package_name", CONTRACT_PACKAGES)
def test_contract_package_files_exist(package_name: str) -> None:
    python_files = sorted(path.name for path in (CONTRACTS_SRC / package_name).glob("*.py"))
    assert python_files, f"contract package {package_name} must contain Python sources"


@pytest.mark.parametrize("package_name", CONTRACT_PACKAGES)
def test_contract_imports_only_stdlib_and_pydantic(package_name: str) -> None:
    violations: dict[str, set[str]] = {}
    for path in (CONTRACTS_SRC / package_name).glob("*.py"):
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
