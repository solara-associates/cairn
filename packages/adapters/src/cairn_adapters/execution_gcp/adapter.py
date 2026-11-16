"""R4-02a: the GCP ``ProviderExecutionPort`` adapter skeleton (ADR-010,
spec §5.4).

This is the first production ``ProviderExecutionPort`` implementation to
exist in this codebase -- structure only. It makes no real GCP SDK import
and no network call anywhere in its own code path
(``test_execution_gcp_package_imports_no_cloud_sdk`` proves this the same
way ``cairn_adapters.provider_core``'s contract test already does for the
read side); every test exercises it against ``GcpExecutionClient``'s fake
implementation and ``FakeTokenProvider``.

It is also, deliberately, **not yet reachable through the gate**:
``GcpProviderExecutionAdapter`` satisfies ``cairn_kernel.execution_gate.
ports.ExecutionAdapterPort``'s shape (an ``adapter_kind`` plus a single
``execute(AdapterRequest)``) so that, structurally, it *could* be passed to
``cairn_kernel.execution_gate.gate.ExecutionGate`` -- and that gate's
``require_deterministic_test_adapter`` guard, which this unit does not
touch, rejects it unconditionally because its ``adapter_kind``
(``GCP_PRODUCTION``) is not ``DETERMINISTIC_TEST``. R1-22's own test suite
already names this exact literal as the look-alike production adapter the
guard must reject
(``packages/kernel/tests/test_execution_gate_ports.py::
test_a_look_alike_production_adapter_is_rejected_by_the_guard``); this
adapter is that shape made real, and the same guard still stops it. Wiring
a real adapter into the gate's allowed set -- the moment ADR-010's "R4:
Class C operations are introduced" actually takes effect for a live
provider -- is a separate, later, cloud-gated unit's job, not this one's.

Credential scoping (ADR-010 Class C rule 5): ``apply`` and ``rollback``
each request a ``TokenProvider``-issued ``ScopedToken`` bound to exactly
this call's revision and operation immediately before calling the client,
and discard it from a ``finally`` block -- the token is requested, used
once, and discarded whether the client call succeeds or raises; nothing
here ever stores one.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairn_kernel.errors import ProviderUnavailableError
from cairn_kernel.execution_gate.ports import AdapterRequest, AdapterResult
from cairn_kernel.hex.primitives import MutationClass

from cairn_adapters.execution_gcp.client import GcpExecutionClient
from cairn_adapters.provider_execution.ports import (
    ApplyRequest,
    ApplyResult,
    ExecutionScope,
    PlanRequest,
    PlanResult,
    ProviderExecutionDescriptor,
    RollbackRequest,
    RollbackResult,
)
from cairn_adapters.provider_execution.token import TokenProvider, TokenRequest

PROVIDER = "gcp"

#: Deliberately the same literal R1-22's test suite already uses as the
#: look-alike production adapter the gate guard must reject -- see this
#: module's docstring.
ADAPTER_KIND = "GCP_PRODUCTION"

_SUPPORTED_MUTATION_CLASSES = frozenset(
    {
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
    }
)

#: Operation-name prefixes ``execute`` dispatches on -- the same synthetic-
#: operation convention R1-22's deterministic test adapter uses
#: (``FIXTURE_OPERATIONS``), just namespaced for this provider instead of
#: fixture-only.
_APPLY_PREFIX = "gcp.apply."
_ROLLBACK_PREFIX = "gcp.rollback."


@dataclass(frozen=True, slots=True)
class GcpProviderExecutionAdapter:
    """Implements both ``ProviderExecutionPort`` (``plan``/``apply``/
    ``rollback``) and the kernel's adapter-agnostic ``ExecutionAdapterPort``
    shape (``adapter_kind`` + ``execute``). Takes its client and token
    provider by injection -- a fake of each is all any test in this unit
    ever supplies."""

    client: GcpExecutionClient
    token_provider: TokenProvider

    adapter_kind: str = ADAPTER_KIND

    @property
    def descriptor(self) -> ProviderExecutionDescriptor:
        return ProviderExecutionDescriptor(
            provider=PROVIDER,
            adapter_kind=self.adapter_kind,
            supported_mutation_classes=_SUPPORTED_MUTATION_CLASSES,
        )

    def plan(self, request: PlanRequest) -> PlanResult:
        """A dry-run preview. No client call, no token request -- planning
        is read-only by construction, and this skeleton has nothing real
        to preview against yet."""

        return PlanResult(
            mutation_class=request.mutation_class,
            preview={"operation": request.scope.operation, "payload": dict(request.payload)},
            reversible=request.mutation_class
            is not MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        )

    def apply(self, request: ApplyRequest) -> ApplyResult:
        token = self._issue_token(request.scope)
        try:
            response = self.client.apply(
                f"/v1/{request.scope.project_id}/apply",
                body=dict(request.payload),
                token=token.value,
            )
        finally:
            self.token_provider.discard(token)

        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"gcp apply for {request.scope.operation!r} failed"
                f" (status {response.status_code})"
            )
        rollback_token = response.body.get("rollback_token")
        return ApplyResult(
            status="APPLIED",
            detail=response.body,
            rollback_token=str(rollback_token) if rollback_token else None,
        )

    def rollback(self, request: RollbackRequest) -> RollbackResult:
        token = self._issue_token(request.scope)
        try:
            response = self.client.rollback(
                f"/v1/{request.scope.project_id}/rollback",
                body={"rollback_token": request.rollback_token, **dict(request.payload)},
                token=token.value,
            )
        finally:
            self.token_provider.discard(token)

        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"gcp rollback for {request.scope.operation!r} failed"
                f" (status {response.status_code})"
            )
        return RollbackResult(status="ROLLED_BACK", detail=response.body)

    def _issue_token(self, scope: ExecutionScope):
        return self.token_provider.issue(
            TokenRequest(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                revision_id=scope.revision_id,
                operation=scope.operation,
            )
        )

    def execute(self, request: AdapterRequest) -> AdapterResult:
        """Satisfies ``ExecutionAdapterPort``'s shape so this adapter
        could, in principle, be passed to ``ExecutionGate`` -- which then
        rejects it via ``require_deterministic_test_adapter`` because
        ``adapter_kind`` is ``GCP_PRODUCTION``, not ``DETERMINISTIC_TEST``.

        Nothing in this codebase calls this method except this adapter's
        own tests; see ``test_the_adapter_is_rejected_by_the_gate_guard``
        and ``test_nothing_outside_this_adapters_own_tests_calls_execute``.
        """

        scope = ExecutionScope(
            tenant_id=str(request.payload.get("tenant_id", "")),
            project_id=str(request.payload.get("project_id", "")),
            revision_id=str(request.payload.get("revision_id", "")),
            operation=request.operation,
        )
        if request.operation.startswith(_APPLY_PREFIX):
            result = self.apply(ApplyRequest(scope=scope, payload=request.payload))
            return AdapterResult(status=result.status, detail=result.detail)
        if request.operation.startswith(_ROLLBACK_PREFIX):
            rollback_token = str(request.payload.get("rollback_token", ""))
            result = self.rollback(
                RollbackRequest(
                    scope=scope, rollback_token=rollback_token, payload=request.payload
                )
            )
            return AdapterResult(status=result.status, detail=result.detail)
        raise ProviderUnavailableError(
            f"gcp execution adapter has no handler for operation {request.operation!r}"
        )


__all__ = ["ADAPTER_KIND", "PROVIDER", "GcpProviderExecutionAdapter"]
