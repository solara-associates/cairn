import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]

VIOLATION_CONFIG = """
[importlinter]
root_packages =
    cairn_kernel
    cairn_contracts

[importlinter:contract:kernel-purity]
name = Kernel imports no contracts
type = forbidden
source_modules = cairn_kernel
forbidden_modules = cairn_contracts
"""


def _write_minimal_tree(root: Path) -> None:
    kernel = root / "cairn_kernel"
    kernel.mkdir()
    (kernel / "__init__.py").write_text("", encoding="utf-8")
    (kernel / "smuggler.py").write_text(
        "import cairn_contracts\n", encoding="utf-8"
    )
    contracts = root / "cairn_contracts"
    contracts.mkdir()
    (contracts / "__init__.py").write_text("", encoding="utf-8")


LINT_IMPORTS = Path(sys.executable).with_name("lint-imports")


def _run_lint_imports(
    config_path: Path, cwd: Path, pythonpath: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **({"PYTHONPATH": str(pythonpath)} if pythonpath else {})}
    return subprocess.run(
        [str(LINT_IMPORTS), "--config", str(config_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )


def test_import_contracts_pass_on_current_tree() -> None:
    result = _run_lint_imports(REPO_ROOT / ".importlinter", REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contracts: 6 kept, 0 broken." in result.stdout


def test_deliberate_violation_fails_the_contracts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_minimal_tree(root)
        config_path = root / ".importlinter"
        config_path.write_text(VIOLATION_CONFIG, encoding="utf-8")
        result = _run_lint_imports(config_path, root, pythonpath=root)
        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "Kernel imports no contracts BROKEN" in output
        assert "cairn_kernel.smuggler -> cairn_contracts" in output
