"""Conformance harness for vertical accelerator packs (R5-06a).

Validates a candidate pack package against three checks, per ADR-002 and
the R5-06a brief:

1. ``domain-purity`` — the same import-linter contract every other module
   in this codebase already satisfies (see ``import_purity.py``).
2. ``manifest`` — a required :class:`~cairn_kits.vertical_packs.manifest.
   PackManifest` (pack id, version, declared ports, declared mutation
   classes reusing ADR-010's ``MutationClass`` enum).
3. ``smoke-test`` — a conventionally-named entry point the pack itself must
   provide, which the harness actually imports and executes.

This module is the harness only — it does not itself ship a real vertical
pack (that is a later, separate unit).
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from cairn_kits.vertical_packs.conventions import (
    MANIFEST_ATTR_NAME,
    MANIFEST_MODULE_NAME,
    SMOKE_ENTRY_POINT_NAME,
    SMOKE_MODULE_NAME,
)
from cairn_kits.vertical_packs.import_purity import check_domain_purity
from cairn_kits.vertical_packs.manifest import PackManifest, validate_manifest_fields

DOMAIN_PURITY_CHECK = "domain-purity"
MANIFEST_CHECK = "manifest"
SMOKE_TEST_CHECK = "smoke-test"

ALL_CHECKS: tuple[str, ...] = (DOMAIN_PURITY_CHECK, MANIFEST_CHECK, SMOKE_TEST_CHECK)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PackConformanceReport:
    package_name: str
    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(result.name for result in self.results if not result.passed)

    def detail_for(self, name: str) -> str:
        for result in self.results:
            if result.name == name:
                return result.detail
        raise KeyError(name)


def _import_fresh(module_name: str, package_root: Path):
    """Import ``module_name`` with ``package_root`` temporarily on ``sys.path``.

    Any previously cached submodules under the pack's own top-level package
    are purged first, so repeated harness runs against fixtures that reuse a
    package name see the current file contents rather than a stale cache
    entry left behind by an earlier run in the same process.
    """
    top_package = module_name.split(".", 1)[0]
    for cached_name in list(sys.modules):
        if cached_name == top_package or cached_name.startswith(top_package + "."):
            del sys.modules[cached_name]

    inserted = str(package_root) not in sys.path
    if inserted:
        sys.path.insert(0, str(package_root))
    try:
        return importlib.import_module(module_name)
    finally:
        if inserted:
            sys.path.remove(str(package_root))


def _check_manifest(package_name: str, package_root: Path) -> CheckResult:
    module_name = f"{package_name}.{MANIFEST_MODULE_NAME}"
    try:
        module = _import_fresh(module_name, package_root)
    except Exception as exc:  # noqa: BLE001 - surfaced as a named check failure
        return CheckResult(MANIFEST_CHECK, False, f"could not import {module_name}: {exc!r}")

    manifest = getattr(module, MANIFEST_ATTR_NAME, None)
    if manifest is None:
        return CheckResult(
            MANIFEST_CHECK,
            False,
            f"{module_name} has no {MANIFEST_ATTR_NAME} attribute",
        )
    if not isinstance(manifest, PackManifest):
        return CheckResult(
            MANIFEST_CHECK,
            False,
            f"{module_name}.{MANIFEST_ATTR_NAME} is not a PackManifest",
        )

    errors = validate_manifest_fields(manifest)
    if errors:
        return CheckResult(MANIFEST_CHECK, False, "; ".join(errors))
    return CheckResult(MANIFEST_CHECK, True, f"manifest ok: {manifest.pack_id}@{manifest.version}")


def _check_smoke_test(package_name: str, package_root: Path) -> CheckResult:
    module_name = f"{package_name}.{SMOKE_MODULE_NAME}"
    try:
        module = _import_fresh(module_name, package_root)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(SMOKE_TEST_CHECK, False, f"could not import {module_name}: {exc!r}")

    entry_point = getattr(module, SMOKE_ENTRY_POINT_NAME, None)
    if not callable(entry_point):
        return CheckResult(
            SMOKE_TEST_CHECK,
            False,
            f"{module_name}.{SMOKE_ENTRY_POINT_NAME} is missing or not callable",
        )

    try:
        entry_point()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(SMOKE_TEST_CHECK, False, f"smoke test raised: {exc!r}")
    return CheckResult(SMOKE_TEST_CHECK, True, "smoke test passed")


def run_conformance(package_name: str, package_root: Path) -> PackConformanceReport:
    """Run all three conformance checks against one candidate pack.

    Args:
        package_name: The pack's top-level importable package name.
        package_root: The directory directly containing that package
            directory.
    """
    purity = check_domain_purity(package_name, package_root)
    results = (
        CheckResult(DOMAIN_PURITY_CHECK, purity.passed, purity.detail),
        _check_manifest(package_name, package_root),
        _check_smoke_test(package_name, package_root),
    )
    return PackConformanceReport(package_name=package_name, results=results)
