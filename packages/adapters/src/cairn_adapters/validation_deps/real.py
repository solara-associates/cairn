"""R3-05: the real "dependency" ``ValidationPort`` adapter.

Spec §5.4: ``ValidationPort | transformation | test/static runner,
fake``. This is the "dependency" check: does the proposed change
introduce a dependency the source repository's own manifest does not
already declare? Scope, named explicitly (the same judgement-call
discipline ``~/solara/lz2026/s726-handover.md``'s ``pattern_version``
reasoning and ``~/solara/lz2026/s728-handover.md``'s role-gating reasoning
both use): ADR-015 scopes this release's transform engine to Terraform/
HCL and Python, so this check only has two kinds of "dependency" to
reason about --

- Python: a top-level module newly imported by the rewritten text that is
  neither a standard-library module nor named in any ``requirements.txt``
  line or ``pyproject.toml`` dependency list already present among the
  fetched files.
- Terraform/HCL: a ``module`` block's ``source`` argument newly present in
  the rewritten text that was not already used by any ``module`` block
  anywhere in the fetched ``.tf``/``.hcl`` files before the change.

Only ever reads the source repository's *own* already-fetched files
(``ValidationRequest.files``) -- never a live package-index lookup, never
a network call of any kind, matching this unit's brief verbatim ("no
network call from any validation adapter ... dependency checks use the
repo's own declared manifest, never a live package-index lookup").
``packages/adapters/tests/test_validation_deps.py``'s construction-proof
test scans this file's source for exactly that.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib

from cairn_contracts.transformation import SourceLanguage
from cairn_modules.transformation.validation import ValidationRequest, ValidationResult

DEPENDENCY_CHECK_ID = "dependency-manifest"

_STDLIB_MODULES: frozenset[str] = frozenset(sys.stdlib_module_names) | {"__future__"}

_MODULE_SOURCE_PATTERN = re.compile(
    r'module\s+"[^"]*"\s*\{[^{}]*?\bsource\s*=\s*"([^"]+)"', re.DOTALL
)

_REQUIREMENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+")


def _requirements_txt_packages(content: str) -> set[str]:
    packages: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = _REQUIREMENT_NAME_PATTERN.match(line)
        if match:
            packages.add(match.group(0).lower().replace("_", "-"))
    return packages


def _pyproject_toml_packages(content: str) -> set[str]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return set()

    packages: set[str] = set()

    def _add_requirement_strings(requirements: object) -> None:
        if not isinstance(requirements, list):
            return
        for requirement in requirements:
            if isinstance(requirement, str):
                match = _REQUIREMENT_NAME_PATTERN.match(requirement.strip())
                if match:
                    packages.add(match.group(0).lower().replace("_", "-"))

    project = data.get("project", {})
    if isinstance(project, dict):
        _add_requirement_strings(project.get("dependencies"))
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group in optional.values():
                _add_requirement_strings(group)

    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        for dep_group in (poetry.get("dependencies"), poetry.get("dev-dependencies")):
            if isinstance(dep_group, dict):
                packages.update(name.lower().replace("_", "-") for name in dep_group if name != "python")

    return packages


def _declared_python_packages(files) -> set[str]:
    declared: set[str] = set()
    for source_file in files:
        if source_file.path == "requirements.txt" or source_file.path.endswith("/requirements.txt"):
            declared |= _requirements_txt_packages(source_file.content)
        elif source_file.path == "pyproject.toml" or source_file.path.endswith("/pyproject.toml"):
            declared |= _pyproject_toml_packages(source_file.content)
    return declared


def _declared_module_sources(files) -> set[str]:
    declared: set[str] = set()
    for source_file in files:
        if source_file.language is SourceLanguage.TERRAFORM:
            declared.update(_MODULE_SOURCE_PATTERN.findall(source_file.content))
    return declared


def _top_level_python_imports(content: str) -> set[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _module_sources(content: str) -> set[str]:
    return set(_MODULE_SOURCE_PATTERN.findall(content))


class DependencyValidationAdapter:
    """The real "dependency" ``ValidationPort`` adapter."""

    def validate(self, request: ValidationRequest) -> tuple[ValidationResult, ...]:
        declared = _declared_python_packages(request.files) | _declared_module_sources(
            request.files
        )
        files_by_path = {source_file.path: source_file for source_file in request.files}

        undeclared: set[str] = set()
        for file_diff in request.diff.files:
            source_file = files_by_path.get(file_diff.source_file_id)
            if source_file is None:
                continue
            if source_file.language is SourceLanguage.PYTHON:
                before = _top_level_python_imports(file_diff.original_content)
                after = _top_level_python_imports(file_diff.rendered_content)
                undeclared |= {
                    module
                    for module in (after - before)
                    if module not in _STDLIB_MODULES and module not in declared
                }
            elif source_file.language is SourceLanguage.TERRAFORM:
                before_sources = _module_sources(file_diff.original_content)
                after_sources = _module_sources(file_diff.rendered_content)
                undeclared |= {
                    source for source in (after_sources - before_sources) if source not in declared
                }

        if undeclared:
            return (
                ValidationResult(
                    check_id=DEPENDENCY_CHECK_ID,
                    passed=False,
                    reason=(
                        "the proposed change introduces a dependency not already declared "
                        f"in the repository's own manifest: {sorted(undeclared)}"
                    ),
                ),
            )
        return (ValidationResult(check_id=DEPENDENCY_CHECK_ID, passed=True),)


__all__ = ["DEPENDENCY_CHECK_ID", "DependencyValidationAdapter"]
