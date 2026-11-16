"""R4-02a: ``ProviderExecutionPort`` contract + GCP adapter skeleton
(ADR-010, spec §5.4).

Covers, against a fake client and a fake token provider (no real GCP SDK,
no network call anywhere):

* the ``ProviderExecutionPort`` contract itself (descriptor, plan/apply/
  rollback) against ``GcpProviderExecutionAdapter``;
* credential scoping -- a token is requested immediately before, and
  discarded immediately after, every ``apply``/``rollback`` call, on both
  the success and the failure path;
* an AST-based construction proof that no cloud SDK (or any non-stdlib,
  non-``cairn_*`` package) is importable from this adapter's source, the
  same convention ``cairn_adapters.provider_core``'s own contract test
  already uses;
* the deliberate break: this adapter structurally satisfies
  ``ExecutionAdapterPort``, and R1-22's own gate guard
  (``require_deterministic_test_adapter``, unchanged by this unit) still
  rejects it -- proving R-GATE-01 ("no production provider adapter
  reachable except through the gate") holds for the first production
  adapter this codebase has ever had.
"""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cairn_adapters.execution_gcp import (
    ADAPTER_KIND,
    GcpExecutionResponse,
    GcpProviderExecutionAdapter,
)
from cairn_adapters.provider_execution import (
    ApplyRequest,
    ExecutionScope,
    FakeTokenProvider,
    PlanRequest,
    RollbackRequest,
)
from cairn_kernel.errors import ConfigurationError, ProviderUnavailableError, ValidationError
from cairn_kernel.execution_gate.ports import AdapterRequest, require_deterministic_test_adapter
from cairn_kernel.hex.primitives import MutationClass
from cairn_modules.execution.gate import ExecutionGate

EXECUTION_GCP_SRC = Path(__file__).parents[1] / "src" / "cairn_adapters" / "execution_gcp"
PROVIDER_EXECUTION_SRC = (
    Path(__file__).parents[1] / "src" / "cairn_adapters" / "provider_execution"
)
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)

SCOPE = ExecutionScope(
    tenant_id="tenant-1",
    project_id="project-1",
    revision_id="revision-1",
    operation="gcp.apply.rotate_firewall_rule",
)


class FakeGcpExecutionClient:
    """Stands in for a real GCP execution HTTP client. Records every call
    (path, body, token) in order, never performs any I/O."""

    def __init__(self) -> None:
        self.apply_calls: list[dict[str, object]] = []
        self.rollback_calls: list[dict[str, object]] = []
        self.apply_status_code = 200
        self.rollback_status_code = 200
        self.apply_body: dict[str, object] = {"rollback_token": "rb-1"}
        self.rollback_body: dict[str, object] = {}
        self.fail_apply = False
        self.fail_rollback = False

    def apply(self, path: str, *, body, token: str) -> GcpExecutionResponse:
        self.apply_calls.append({"path": path, "body": body, "token": token})
        if self.fail_apply:
            raise RuntimeError("simulated gcp apply outage")
        return GcpExecutionResponse(status_code=self.apply_status_code, body=self.apply_body)

    def rollback(self, path: str, *, body, token: str) -> GcpExecutionResponse:
        self.rollback_calls.append({"path": path, "body": body, "token": token})
        if self.fail_rollback:
            raise RuntimeError("simulated gcp rollback outage")
        return GcpExecutionResponse(
            status_code=self.rollback_status_code, body=self.rollback_body
        )


def _clock() -> datetime:
    return NOW


def make_adapter(
    client: FakeGcpExecutionClient | None = None,
    token_provider: FakeTokenProvider | None = None,
) -> tuple[GcpProviderExecutionAdapter, FakeGcpExecutionClient, FakeTokenProvider]:
    client = client or FakeGcpExecutionClient()
    token_provider = token_provider or FakeTokenProvider(clock=_clock)
    adapter = GcpProviderExecutionAdapter(client=client, token_provider=token_provider)
    return adapter, client, token_provider


# --- ProviderExecutionPort contract ----------------------------------------


def test_descriptor_identifies_gcp_and_the_production_adapter_kind() -> None:
    adapter, _, _ = make_adapter()
    descriptor = adapter.descriptor
    assert descriptor.provider == "gcp"
    assert descriptor.adapter_kind == ADAPTER_KIND == "GCP_PRODUCTION"
    assert descriptor.supported_mutation_classes == frozenset(
        {
            MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        }
    )


def test_descriptor_rejects_read_only_as_a_supported_mutation_class() -> None:
    from cairn_adapters.provider_execution import ProviderExecutionDescriptor

    with pytest.raises(ValidationError):
        ProviderExecutionDescriptor(
            provider="gcp",
            adapter_kind=ADAPTER_KIND,
            supported_mutation_classes=frozenset({MutationClass.READ_ONLY}),
        )


def test_plan_returns_a_preview_without_touching_the_client_or_a_token() -> None:
    adapter, client, token_provider = make_adapter()
    result = adapter.plan(
        PlanRequest(
            scope=SCOPE,
            mutation_class=MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
            payload={"rule": "allow-443"},
        )
    )
    assert result.mutation_class is MutationClass.REVERSIBLE_EXTERNAL_MUTATION
    assert result.reversible is True
    assert client.apply_calls == []
    assert client.rollback_calls == []
    assert token_provider.issued == ()


def test_plan_marks_an_irreversible_mutation_as_not_reversible() -> None:
    adapter, _, _ = make_adapter()
    result = adapter.plan(
        PlanRequest(
            scope=SCOPE,
            mutation_class=MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
            payload={},
        )
    )
    assert result.reversible is False


def test_apply_calls_the_client_with_the_issued_token_and_returns_a_rollback_token() -> None:
    adapter, client, _ = make_adapter()
    result = adapter.apply(ApplyRequest(scope=SCOPE, payload={"rule": "allow-443"}))

    assert result.status == "APPLIED"
    assert result.rollback_token == "rb-1"
    assert len(client.apply_calls) == 1
    call = client.apply_calls[0]
    assert call["path"] == f"/v1/{SCOPE.project_id}/apply"
    assert call["body"] == {"rule": "allow-443"}
    assert call["token"] == "fake-token-1"


def test_apply_raises_provider_unavailable_on_a_non_200_response() -> None:
    adapter, client, _ = make_adapter()
    client.apply_status_code = 503
    with pytest.raises(ProviderUnavailableError):
        adapter.apply(ApplyRequest(scope=SCOPE, payload={}))


def test_rollback_calls_the_client_with_the_rollback_token() -> None:
    adapter, client, _ = make_adapter()
    result = adapter.rollback(
        RollbackRequest(scope=SCOPE, rollback_token="rb-1", payload={})
    )
    assert result.status == "ROLLED_BACK"
    call = client.rollback_calls[0]
    assert call["body"]["rollback_token"] == "rb-1"


def test_rollback_request_rejects_a_blank_rollback_token() -> None:
    with pytest.raises(ValidationError):
        RollbackRequest(scope=SCOPE, rollback_token="   ", payload={})


# --- credential scoping (ADR-010 Class C rule 5) ---------------------------


def test_apply_issues_exactly_one_token_scoped_to_the_revision_and_operation() -> None:
    adapter, _, token_provider = make_adapter()
    adapter.apply(ApplyRequest(scope=SCOPE, payload={}))

    assert len(token_provider.issued) == 1
    token = token_provider.issued[0]
    assert token.revision_id == SCOPE.revision_id
    assert token.operation == SCOPE.operation


def test_apply_discards_the_token_immediately_after_a_successful_call() -> None:
    adapter, _, token_provider = make_adapter()
    adapter.apply(ApplyRequest(scope=SCOPE, payload={}))

    assert len(token_provider.discarded) == 1
    assert token_provider.discarded[0] is token_provider.issued[0]


def test_apply_discards_the_token_even_when_the_client_raises() -> None:
    adapter, client, token_provider = make_adapter()
    client.fail_apply = True

    with pytest.raises(RuntimeError):
        adapter.apply(ApplyRequest(scope=SCOPE, payload={}))

    assert len(token_provider.issued) == 1
    assert len(token_provider.discarded) == 1
    assert token_provider.discarded[0] is token_provider.issued[0]


def test_rollback_discards_the_token_even_when_the_client_raises() -> None:
    adapter, client, token_provider = make_adapter()
    client.fail_rollback = True

    with pytest.raises(RuntimeError):
        adapter.rollback(RollbackRequest(scope=SCOPE, rollback_token="rb-1", payload={}))

    assert len(token_provider.issued) == 1
    assert len(token_provider.discarded) == 1


def test_a_token_is_never_reused_across_two_apply_calls() -> None:
    adapter, _, token_provider = make_adapter()
    adapter.apply(ApplyRequest(scope=SCOPE, payload={}))
    adapter.apply(ApplyRequest(scope=SCOPE, payload={}))

    assert len(token_provider.issued) == 2
    first, second = token_provider.issued
    assert first.value != second.value


def test_a_scoped_token_expires_after_it_is_issued() -> None:
    token_provider = FakeTokenProvider(clock=_clock, ttl=timedelta(seconds=30))
    adapter, _, _ = make_adapter(token_provider=token_provider)
    adapter.apply(ApplyRequest(scope=SCOPE, payload={}))

    token = token_provider.issued[0]
    assert token.expires_at == NOW + timedelta(seconds=30)
    assert token.expires_at > token.issued_at


# --- execute() / ExecutionAdapterPort shape --------------------------------


def test_execute_dispatches_an_apply_operation() -> None:
    adapter, client, _ = make_adapter()
    result = adapter.execute(
        AdapterRequest(
            operation="gcp.apply.rotate_firewall_rule",
            payload={
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "revision_id": "revision-1",
                "rule": "allow-443",
            },
        )
    )
    assert result.status == "APPLIED"
    assert len(client.apply_calls) == 1


def test_execute_dispatches_a_rollback_operation() -> None:
    adapter, client, _ = make_adapter()
    result = adapter.execute(
        AdapterRequest(
            operation="gcp.rollback.rotate_firewall_rule",
            payload={
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "revision_id": "revision-1",
                "rollback_token": "rb-1",
            },
        )
    )
    assert result.status == "ROLLED_BACK"
    assert len(client.rollback_calls) == 1


def test_execute_rejects_an_operation_it_has_no_handler_for() -> None:
    adapter, _, _ = make_adapter()
    with pytest.raises(ProviderUnavailableError):
        adapter.execute(
            AdapterRequest(
                operation="gcp.delete_everything",
                payload={
                    "tenant_id": "tenant-1",
                    "project_id": "project-1",
                    "revision_id": "revision-1",
                },
            )
        )


# --- the deliberate break: unreachable outside the gate (R-GATE-01) -------


def test_the_adapter_satisfies_the_execution_adapter_port_shape() -> None:
    """Structural precondition for the next test: this adapter really does
    look like something ``ExecutionGate`` could be handed."""

    adapter, _, _ = make_adapter()
    assert adapter.adapter_kind == "GCP_PRODUCTION"
    assert callable(adapter.execute)


def test_the_gate_guard_rejects_this_adapter_directly() -> None:
    adapter, _, _ = make_adapter()
    with pytest.raises(ConfigurationError):
        require_deterministic_test_adapter(adapter)


def test_execution_gate_refuses_to_construct_with_this_adapter() -> None:
    """R-GATE-01: no production provider adapter is reachable except
    through the gate -- and here, not even through it. Constructing the
    one object every Class C dispatch goes through with this unit's new
    adapter raises before any audit sink, idempotency store or clock is
    even touched; nothing else in this codebase can smuggle this adapter
    into a live gate."""

    adapter, _, _ = make_adapter()

    class _UnusedAuditSink:
        def append(self, entry: object) -> str:  # pragma: no cover
            raise AssertionError("must never be called")

    class _UnusedIdempotencyStore:
        def get(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
            raise AssertionError("must never be called")

        def put(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
            raise AssertionError("must never be called")

    class _UnusedClock:
        def now(self) -> datetime:  # pragma: no cover
            raise AssertionError("must never be called")

    with pytest.raises(ConfigurationError):
        ExecutionGate(
            adapter=adapter,
            audit_sink=_UnusedAuditSink(),  # type: ignore[arg-type]
            idempotency_store=_UnusedIdempotencyStore(),  # type: ignore[arg-type]
            clock=_UnusedClock(),  # type: ignore[arg-type]
        )


# --- no cloud SDK import anywhere in this unit's code path -----------------

# ``cairn_modules`` was added for 790 (R4-04a)'s ``provider_execution.recovery``
# module, which legitimately reuses the domain-model execution state machine
# (``cairn_modules.execution.model``) -- the same precedent already set for
# this same ``PROVIDER_EXECUTION_SRC`` directory by
# ``test_terraform_plan_orchestration.py``'s own allowlist. Domain-model
# reuse is not a cloud SDK/network import; this allowlist still rejects any
# actual cloud SDK or network-shaped import.
_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "cairn_adapters",
    "cairn_kernel",
    "cairn_modules",
    "collections",
    "dataclasses",
    "datetime",
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


@pytest.mark.parametrize("package_dir", [EXECUTION_GCP_SRC, PROVIDER_EXECUTION_SRC])
def test_no_cloud_sdk_or_network_import_anywhere_in_this_units_packages(
    package_dir: Path,
) -> None:
    violations: dict[str, set[str]] = {}
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = _imported_roots(tree)
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in _ALLOWED_IMPORT_ROOTS
        }
        if disallowed:
            violations[f"{package_dir.name}/{path.name}"] = disallowed
    assert not violations, f"disallowed (cloud SDK / network) imports: {violations}"


def test_no_network_call_shaped_source_anywhere_in_this_units_packages() -> None:
    """Belt-and-braces alongside the import-scan test: the module source
    itself must not even mention a network-call-shaped name, so a call
    smuggled in through an already-imported module (rather than a new
    import) would still be caught."""

    forbidden_substrings = ("socket.", "urllib", "http.client", "subprocess")
    for package_dir in (EXECUTION_GCP_SRC, PROVIDER_EXECUTION_SRC):
        for path in sorted(package_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for bad in forbidden_substrings:
                assert bad not in source, f"{path}: found forbidden substring {bad!r}"
