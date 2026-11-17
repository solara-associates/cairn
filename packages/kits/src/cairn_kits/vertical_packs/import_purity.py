"""Domain-purity check for vertical accelerator packs.

Reuses import-linter's own CLI (``lint-imports``) rather than reimplementing
import-graph analysis. This mirrors the exact approach the repo's own
``tests/contract/test_import_contracts.py`` already uses to exercise the
root ``.importlinter`` file: generate a scoped config, point ``lint-imports``
at the candidate package via ``PYTHONPATH``, and read its exit code.

The forbidden-module list below mirrors the root ``.importlinter``'s
``domain-purity`` contract (``cairn_modules`` must not import
``cairn_adapters``/``cairn_api``/etc) — the same rule every other module in
this codebase already satisfies, applied here to one candidate pack package
instead of to ``cairn_modules`` as a whole.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Mirrors the root `.importlinter`'s `domain-purity` contract.
FORBIDDEN_MODULES: tuple[str, ...] = (
    "cairn_adapters",
    "cairn_api",
    "cairn_worker",
    "cairn_scheduler",
    "cairn_mcp_gateway",
    "cairn_cli",
)

_LINT_IMPORTS = Path(sys.executable).with_name("lint-imports")

_CONFIG_TEMPLATE = """\
[importlinter]
root_packages =
    {package_name}
include_external_packages = True

[importlinter:contract:pack-domain-purity]
name = Vertical pack imports no adapters or applications
type = forbidden
source_modules = {package_name}
forbidden_modules =
    {forbidden}
"""


@dataclass(frozen=True, slots=True)
class ImportPurityResult:
    passed: bool
    detail: str


def check_domain_purity(package_name: str, package_root: Path) -> ImportPurityResult:
    """Run import-linter's domain-purity contract against one pack package.

    Args:
        package_name: The pack's top-level importable package name.
        package_root: The directory that directly contains that package
            directory (i.e. what would sit on ``PYTHONPATH``/``sys.path``).
    """
    config = _CONFIG_TEMPLATE.format(
        package_name=package_name,
        forbidden="\n    ".join(FORBIDDEN_MODULES),
    )
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / ".importlinter"
        config_path.write_text(config, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(package_root)}
        result = subprocess.run(
            [str(_LINT_IMPORTS), "--config", str(config_path)],
            capture_output=True,
            text=True,
            cwd=package_root,
            env=env,
            check=False,
        )

    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return ImportPurityResult(passed=True, detail=output or "no violations")
    return ImportPurityResult(passed=False, detail=output or "lint-imports failed")
