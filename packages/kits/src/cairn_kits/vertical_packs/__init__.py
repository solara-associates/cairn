"""Vertical accelerator pack conformance harness (R5-06a).

See ``harness.py`` for the three checks a candidate pack must pass:
``domain-purity``, ``manifest`` and ``smoke-test``.
"""

from cairn_kits.vertical_packs.conventions import (
    MANIFEST_ATTR_NAME,
    MANIFEST_MODULE_NAME,
    SMOKE_ENTRY_POINT_NAME,
    SMOKE_MODULE_NAME,
)
from cairn_kits.vertical_packs.harness import (
    ALL_CHECKS,
    DOMAIN_PURITY_CHECK,
    MANIFEST_CHECK,
    SMOKE_TEST_CHECK,
    CheckResult,
    PackConformanceReport,
    run_conformance,
)
from cairn_kits.vertical_packs.manifest import PackManifest, validate_manifest_fields

__all__ = [
    "ALL_CHECKS",
    "DOMAIN_PURITY_CHECK",
    "MANIFEST_ATTR_NAME",
    "MANIFEST_CHECK",
    "MANIFEST_MODULE_NAME",
    "SMOKE_ENTRY_POINT_NAME",
    "SMOKE_MODULE_NAME",
    "SMOKE_TEST_CHECK",
    "CheckResult",
    "PackConformanceReport",
    "PackManifest",
    "run_conformance",
    "validate_manifest_fields",
]
