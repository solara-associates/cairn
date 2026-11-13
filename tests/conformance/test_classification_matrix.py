"""R0-19: every operation that exists today must be classified.

This test discovers the real surfaces in the running codebase (API routes,
declared event types) and cross-checks them against
``cairn_kernel.classification.matrix.OPERATIONS``. A new, unclassified
operation makes this test fail; removing an entry from the matrix for a
surface that still exists makes this test fail the same way.
"""

import re
from pathlib import Path

from cairn_api import create_app as create_api_app
from cairn_contracts.events.model import KNOWN_EVENT_TYPES
from cairn_kernel.classification import SurfaceKind, operations_by_name, require_classified
from cairn_kernel.classification.matrix import OPERATIONS
from cairn_worker import create_app as create_worker_app

# Routes FastAPI adds itself (OpenAPI schema, docs UI) are transport
# framework introspection, not a CAIRN-defined operation.
_FRAMEWORK_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def _discover_api_operations() -> set[tuple[str, str, str]]:
    apps = {"api": create_api_app(), "worker": create_worker_app()}
    discovered: set[tuple[str, str, str]] = set()
    for service, app in apps.items():
        for route in app.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None or path in _FRAMEWORK_PATHS:
                continue
            for method in methods:
                if method == "HEAD":
                    continue
                discovered.add((service, method, path))
    return discovered


def test_every_live_api_route_is_classified() -> None:
    index = operations_by_name(OPERATIONS)
    discovered = _discover_api_operations()
    assert discovered, "expected at least the health/readiness routes to exist"
    for service, method, path in discovered:
        require_classified(index, SurfaceKind.API, f"{service}.{method} {path}")


def test_every_declared_event_type_is_classified() -> None:
    index = operations_by_name(OPERATIONS)
    assert KNOWN_EVENT_TYPES, "expected at least one declared event type"
    for event_type in KNOWN_EVENT_TYPES:
        require_classified(index, SurfaceKind.EVENT, event_type)


def test_matrix_has_no_stale_api_entries() -> None:
    """Catches the opposite drift: a matrix entry for an API route that no longer exists."""
    discovered = {f"{service}.{method} {path}" for service, method, path in _discover_api_operations()}
    matrix_api_names = {entry.name for entry in OPERATIONS if entry.surface is SurfaceKind.API}
    assert matrix_api_names <= discovered


def test_matrix_has_no_stale_event_entries() -> None:
    matrix_event_names = {entry.name for entry in OPERATIONS if entry.surface is SurfaceKind.EVENT}
    assert matrix_event_names <= KNOWN_EVENT_TYPES


def test_no_mcp_tool_or_resource_exists_yet() -> None:
    """apps/mcp-gateway is a docstring-only stub; this fails loudly the day that changes,
    which is the signal to add real MCP_TOOL/MCP_RESOURCE classification entries."""
    import cairn_mcp_gateway

    source = Path(cairn_mcp_gateway.__file__).read_text(encoding="utf-8")
    assert re.match(r'^"""[^"]*"""\s*$', source), (
        "apps/mcp-gateway now has real code; classify its tools/resources in"
        " cairn_kernel.classification.matrix before this test is allowed to pass"
    )
