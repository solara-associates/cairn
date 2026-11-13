"""R1-22: kernel execution-gate primitives (ADR-010).

Covers the mutation-class-agnostic half of the gate that lives in
``cairn_kernel.execution_gate``: the adapter port guard (no production
adapter reachable, by any route), scoped idempotency (R-IDEM-01), and the
"no execution credentials reachable" property of the deterministic test
adapter. The full propose -> approve -> authorize -> execute -> record
lifecycle, which composes these with R1-21's state machines, is covered in
``packages/modules/tests/test_execution_gate.py``.
"""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest
from cairn_kernel.errors import ConfigurationError, IdempotencyConflictError
from cairn_kernel.execution_gate import (
    AdapterRequest,
    AdapterResult,
    DeterministicTestExecutionAdapter,
    IdempotencyRecord,
    IdempotencyScope,
    InMemoryIdempotencyStore,
    canonical_request_hash,
    check_idempotency,
    require_deterministic_test_adapter,
)  # InMemoryIdempotencyStore: the kernel's own in-memory IdempotencyStorePort
from cairn_kernel.hex.primitives import ProjectId, TenantId

TENANT = TenantId("11111111-1111-1111-1111-111111111111")
PROJECT = ProjectId("22222222-2222-2222-2222-222222222222")
EXECUTION_GATE_SRC = Path(__file__).parents[1] / "src" / "cairn_kernel" / "execution_gate"


# --- no production adapter reachable --------------------------------------


def test_deterministic_test_adapter_satisfies_the_guard() -> None:
    require_deterministic_test_adapter(DeterministicTestExecutionAdapter())  # does not raise


class _LookAlikeProductionAdapter:
    """Structurally satisfies ``ExecutionAdapterPort`` (has ``execute``) but
    is not the deterministic test adapter — exactly the shape a smuggled-in
    "production" adapter would have. The guard must reject it regardless of
    what ``adapter_kind`` (if any) it claims."""

    adapter_kind = "GCP_PRODUCTION"

    def execute(self, request: AdapterRequest) -> AdapterResult:  # pragma: no cover
        raise AssertionError("a look-alike production adapter must never be called")


def test_a_look_alike_production_adapter_is_rejected_by_the_guard() -> None:
    with pytest.raises(ConfigurationError):
        require_deterministic_test_adapter(_LookAlikeProductionAdapter())


class _AdapterWithNoKind:
    def execute(self, request: AdapterRequest) -> AdapterResult:  # pragma: no cover
        raise AssertionError("must never be called")


def test_an_adapter_with_no_adapter_kind_at_all_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        require_deterministic_test_adapter(_AdapterWithNoKind())


def test_the_guard_cannot_be_satisfied_by_any_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-010: "no code path, config flag, or env var may swap in a
    production adapter". The guard is a pure function of the adapter object
    it is given — setting any plausible override variable must not change
    its verdict on a look-alike adapter."""

    monkeypatch.setenv("CAIRN_EXECUTION_ADAPTER", "production")
    monkeypatch.setenv("CAIRN_ALLOW_PRODUCTION_ADAPTER", "true")
    with pytest.raises(ConfigurationError):
        require_deterministic_test_adapter(_LookAlikeProductionAdapter())


# --- no execution credentials reachable ------------------------------------

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "cairn_kernel",
    "collections",
    "dataclasses",
    "datetime",
    "hashlib",
    "types",
    "typing",
}


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_execution_gate_package_imports_only_stdlib_and_kernel() -> None:
    """No network client, cloud SDK or credential library is importable from
    this package in R1 — there is nothing here for execution credentials to
    be read into, let alone reached through."""

    violations: dict[str, set[str]] = {}
    for path in sorted(EXECUTION_GATE_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in _ALLOWED_IMPORT_ROOTS
        }
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"disallowed imports in execution_gate: {violations}"


def test_execution_gate_package_never_touches_the_environment() -> None:
    """``os.environ``/``os.getenv`` would be the shape of a config-flag
    adapter swap; assert the source simply does not contain one."""

    for path in sorted(EXECUTION_GATE_SRC.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "os.environ" not in source
        assert "getenv" not in source


def test_deterministic_test_adapter_exposes_no_credential_like_attribute() -> None:
    adapter = DeterministicTestExecutionAdapter()
    forbidden_substrings = ("secret", "credential", "token", "password", "key_id", "api_key")
    for attribute in dir(adapter):
        if attribute.startswith("__"):
            continue
        lowered = attribute.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), attribute


def test_deterministic_test_adapter_rejects_an_operation_outside_its_fixtures() -> None:
    from cairn_kernel.errors import ProviderUnavailableError

    adapter = DeterministicTestExecutionAdapter()
    with pytest.raises(ProviderUnavailableError):
        adapter.execute(AdapterRequest(operation="not_a_fixture", payload={}))


# --- scoped idempotency (R-IDEM-01) ----------------------------------------


def _scope(key: str = "key-1", operation: str = "fixture.rotate_api_key") -> IdempotencyScope:
    return IdempotencyScope(tenant_id=TENANT, project_id=PROJECT, operation=operation, key=key)


def test_canonical_request_hash_is_stable_under_key_order() -> None:
    first = canonical_request_hash({"a": 1, "b": 2})
    second = canonical_request_hash({"b": 2, "a": 1})
    assert first == second


def test_canonical_request_hash_differs_for_a_different_payload() -> None:
    assert canonical_request_hash({"a": 1}) != canonical_request_hash({"a": 2})


def test_no_record_is_not_a_replay() -> None:
    store = InMemoryIdempotencyStore()
    decision = check_idempotency(store, _scope(), "hash-1", now=datetime.now(UTC))
    assert decision.is_replay is False
    assert decision.record is None


def test_a_live_record_with_the_same_hash_is_a_replay() -> None:
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    record = IdempotencyRecord(
        scope=_scope(),
        request_hash="hash-1",
        result=MappingProxyType({"status": "APPLIED"}),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    store.put(record)
    decision = check_idempotency(store, _scope(), "hash-1", now=now)
    assert decision.is_replay is True
    assert decision.record is record


def test_a_live_record_with_a_different_hash_is_a_conflict() -> None:
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    store.put(
        IdempotencyRecord(
            scope=_scope(),
            request_hash="hash-1",
            result=MappingProxyType({}),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    with pytest.raises(IdempotencyConflictError):
        check_idempotency(store, _scope(), "hash-2", now=now)


def test_an_expired_record_is_treated_as_absent() -> None:
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    store.put(
        IdempotencyRecord(
            scope=_scope(),
            request_hash="hash-1",
            result=MappingProxyType({}),
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    decision = check_idempotency(store, _scope(), "hash-2", now=now)
    assert decision.is_replay is False


def test_different_keys_in_the_same_scope_are_independent() -> None:
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    store.put(
        IdempotencyRecord(
            scope=_scope(key="key-1"),
            request_hash="hash-1",
            result=MappingProxyType({}),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    decision = check_idempotency(store, _scope(key="key-2"), "hash-1", now=now)
    assert decision.is_replay is False


def test_the_same_key_in_a_different_project_is_a_different_scope() -> None:
    store = InMemoryIdempotencyStore()
    now = datetime.now(UTC)
    store.put(
        IdempotencyRecord(
            scope=_scope(),
            request_hash="hash-1",
            result=MappingProxyType({}),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    other_project_scope = IdempotencyScope(
        tenant_id=TENANT,
        project_id=ProjectId("33333333-3333-3333-3333-333333333333"),
        operation="fixture.rotate_api_key",
        key="key-1",
    )
    decision = check_idempotency(store, other_project_scope, "hash-1", now=now)
    assert decision.is_replay is False


def test_idempotency_scope_rejects_a_blank_key() -> None:
    with pytest.raises(ValueError):
        IdempotencyScope(tenant_id=TENANT, project_id=PROJECT, operation="op", key="  ")


def test_idempotency_scope_rejects_a_blank_operation() -> None:
    with pytest.raises(ValueError):
        IdempotencyScope(tenant_id=TENANT, project_id=PROJECT, operation="  ", key="key")
