"""Naming conventions a vertical accelerator pack must follow.

The harness (``cairn_kits.vertical_packs.harness``) looks for these
conventionally-named modules and attributes inside a candidate pack's own
top-level package. A pack that uses different names is not discoverable and
fails the relevant check — there is no fallback discovery.
"""

from __future__ import annotations

#: Submodule, within the pack's package, holding its manifest.
MANIFEST_MODULE_NAME = "manifest"
#: Module-level attribute on that submodule: a ``PackManifest`` instance.
MANIFEST_ATTR_NAME = "MANIFEST"

#: Submodule, within the pack's package, holding its smoke test.
SMOKE_MODULE_NAME = "smoke"
#: Zero-argument callable on that submodule. Raising means "failed".
SMOKE_ENTRY_POINT_NAME = "run_smoke_test"
