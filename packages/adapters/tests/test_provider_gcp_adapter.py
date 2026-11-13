"""R1-05: the GCP inventory adapter -- contract conformance plus the
read-only-scope refusal that ADR-010 / R1-02 require before any collection.

No live GCP project is called: ``FakeGcpHttpClient`` below stands in for
the GCP API client, keyed by (path, params) so the walk is deterministic
regardless of how many times the contract suite re-runs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count

import pytest
from cairn_adapters.provider_core.contract import (
    assert_inventory_contract,
    run_provider_contract,
)
from cairn_adapters.provider_core.ports import (
    InventoryRequest,
    ProviderCapability,
    ProviderConnection,
)
from cairn_adapters.provider_gcp.adapter import GcpInventoryAdapter
from cairn_adapters.provider_gcp.client import GcpApiResponse, RateLimiter, RetryConfig
from cairn_kernel.errors import (
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from cairn_kernel.security.audit import AuditEntry
from cairn_modules.connections import ConnectionRegistry

TENANT = "tenant-1"
PROJECT = "project-1"
GCP_PROJECT = "gcp-project-123"
NOW = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self._counter = count(1)

    def append(self, entry: AuditEntry) -> str:
        self.entries.append(entry)
        return f"audit-{next(self._counter)}"


@dataclass
class FakeGcpHttpClient:
    """Deterministic stand-in for a real GCP API client.

    Keyed by ``(path, sorted params)`` rather than call order, so repeated
    full walks of the same inventory (as the pagination contract's
    determinism check performs) always see the same answer.
    """

    responses: dict[tuple[str, tuple[tuple[str, str], ...]], GcpApiResponse]
    calls: list[str] = field(default_factory=list)

    def get(self, path, *, params=None) -> GcpApiResponse:
        self.calls.append(path)
        key = (path, tuple(sorted((params or {}).items())))
        try:
            return self.responses[key]
        except KeyError as exc:  # pragma: no cover - test wiring error
            raise AssertionError(f"no fake gcp response for {key}") from exc


def _resource_item(resource_id: str, service: str, *, name: str | None = None) -> dict:
    return {
        "id": resource_id,
        "service": service,
        "resourceType": f"{service}.instance",
        "name": name if name is not None else resource_id,
        "tags": {"env": "dev"},
    }


def _connection(connection_id: str = "conn-1") -> ProviderConnection:
    return ProviderConnection(
        connection_id=connection_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="gcp",
        account_id=GCP_PROJECT,
        credential_ref="secret://gcp/conn-1",
    )


def _registry_with_connection(
    *, connection_id: str = "conn-1", revoked: bool = False
) -> ConnectionRegistry:
    registry = ConnectionRegistry(audit_sink=InMemoryAuditSink())
    registry.create(
        connection_id=connection_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="gcp",
        account_id=GCP_PROJECT,
        secret="service-account-key",
        actor_id="user-1",
    )
    if revoked:
        registry.revoke(connection_id, actor_id="user-1")
    return registry


def _fake_client(
    *, extra: dict[tuple[str, tuple[tuple[str, str], ...]], GcpApiResponse] | None = None
) -> FakeGcpHttpClient:
    responses: dict = {
        (f"/v1/projects/{GCP_PROJECT}", ()): GcpApiResponse(200, {"id": GCP_PROJECT}),
        (f"/compute/v1/projects/{GCP_PROJECT}/regions", ()): GcpApiResponse(
            200, {"items": [{"name": "europe-west2"}, {"name": "us-east1"}]}
        ),
        (
            f"/compute/v1/projects/{GCP_PROJECT}/regions/europe-west2/resources",
            (),
        ): GcpApiResponse(
            200,
            {
                "items": [
                    _resource_item("res-1", "compute"),
                    _resource_item("res-3", "storage"),
                ]
            },
        ),
        (
            f"/compute/v1/projects/{GCP_PROJECT}/regions/us-east1/resources",
            (),
        ): GcpApiResponse(
            200,
            {"items": [_resource_item("res-2", "compute")]},
        ),
    }
    if extra:
        responses.update(extra)
    return FakeGcpHttpClient(responses=responses)


def _adapter(client: FakeGcpHttpClient, registry: ConnectionRegistry) -> GcpInventoryAdapter:
    return GcpInventoryAdapter(
        client=client,
        registry=registry,
        rate_limiter=RateLimiter(max_calls_per_second=1_000, sleep=lambda seconds: None),
        retry_config=RetryConfig(max_attempts=3, base_delay_seconds=0.01),
        clock=lambda: NOW,
    )


def test_descriptor_declares_inventory_only_and_read_only() -> None:
    adapter = _adapter(_fake_client(), _registry_with_connection())
    descriptor = adapter.descriptor
    assert descriptor.provider == "gcp"
    assert descriptor.read_only
    assert descriptor.capabilities == frozenset({ProviderCapability.INVENTORY})


def test_gcp_adapter_satisfies_the_inventory_contract() -> None:
    adapter = _adapter(_fake_client(), _registry_with_connection())
    request = InventoryRequest(connection=_connection(), page_size=2)
    ids = assert_inventory_contract(
        adapter, request, expected_resource_ids=("res-1", "res-2", "res-3")
    )
    assert ids == ("res-1", "res-2", "res-3")


def test_run_provider_contract_reports_the_inventory_count() -> None:
    adapter = _adapter(_fake_client(), _registry_with_connection())
    counts = run_provider_contract(
        adapter, inventory=InventoryRequest(connection=_connection(), page_size=2)
    )
    assert counts == {"inventory": 3}


def test_gcp_adapter_filters_by_requested_service_and_reports_coverage() -> None:
    adapter = _adapter(_fake_client(), _registry_with_connection())
    request = InventoryRequest(connection=_connection(), services=("storage", "database"))
    page = adapter.read_inventory(request)
    assert [resource.resource_id for resource in page.resources] == ["res-3"]
    assert page.coverage.observed_services == ("storage",)
    assert page.coverage.skipped_services == ("database",)
    assert not page.coverage.complete


def test_gcp_adapter_refuses_when_connection_provider_does_not_match() -> None:
    adapter = _adapter(_fake_client(), _registry_with_connection())
    other = ProviderConnection(
        connection_id="conn-1",
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="aws",
        account_id=GCP_PROJECT,
        credential_ref="secret://aws/conn-1",
    )
    with pytest.raises(ValidationError):
        adapter.read_inventory(InventoryRequest(connection=other))


def test_gcp_adapter_refuses_an_unknown_connection() -> None:
    adapter = _adapter(_fake_client(), ConnectionRegistry(audit_sink=InMemoryAuditSink()))
    with pytest.raises(NotFoundError):
        adapter.read_inventory(InventoryRequest(connection=_connection()))


def test_gcp_adapter_refuses_a_revoked_connection() -> None:
    registry = _registry_with_connection(revoked=True)
    adapter = _adapter(_fake_client(), registry)
    with pytest.raises(ValidationError):
        adapter.read_inventory(InventoryRequest(connection=_connection()))


def test_gcp_adapter_refuses_to_collect_when_the_probe_is_unreachable() -> None:
    client = _fake_client(
        extra={
            (f"/v1/projects/{GCP_PROJECT}", ()): GcpApiResponse(500, {}),
        }
    )
    adapter = _adapter(client, _registry_with_connection())
    with pytest.raises(ProviderUnavailableError):
        adapter.read_inventory(InventoryRequest(connection=_connection()))
    # Refused before any region/resource call was made.
    assert all("regions" not in call for call in client.calls)


def test_gcp_adapter_raises_cleanly_when_a_region_call_keeps_failing() -> None:
    client = _fake_client(
        extra={
            (
                f"/compute/v1/projects/{GCP_PROJECT}/regions/us-east1/resources",
                (),
            ): GcpApiResponse(503, {}),
        }
    )
    adapter = _adapter(client, _registry_with_connection())
    with pytest.raises(ProviderUnavailableError):
        adapter.read_inventory(InventoryRequest(connection=_connection()))
