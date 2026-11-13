import ast
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cairn_adapters.provider_core import (
    BillingRequest,
    CoverageReport,
    FakeProviderAdapter,
    InventoryPage,
    InventoryRequest,
    PostureRequest,
    ProviderCapability,
    ProviderConnection,
    ProviderDescriptor,
    assert_inventory_contract,
    run_provider_contract,
)
from cairn_contracts.estate import (
    CostRecord,
    FactStatus,
    Finding,
    Outcome,
    Provenance,
    Resource,
)
from cairn_kernel.errors import ProviderUnavailableError, ValidationError

NOW = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
TENANT = "tenant-1"
PROJECT = "project-1"
ACCOUNT = "account-1"
PROVIDER_CORE = (
    Path(__file__).parents[1] / "src" / "cairn_adapters" / "provider_core"
)

CONNECTION = ProviderConnection(
    connection_id="conn-1",
    tenant_id=TENANT,
    project_id=PROJECT,
    provider="fake",
    account_id=ACCOUNT,
    credential_ref="secret://fake/conn-1",
)
INVENTORY_REQUEST = InventoryRequest(connection=CONNECTION, page_size=2)
BILLING_REQUEST = BillingRequest(
    connection=CONNECTION,
    period_start=NOW,
    period_end=NOW + timedelta(days=2),
    page_size=1,
)
POSTURE_REQUEST = PostureRequest(connection=CONNECTION, page_size=2)


def provenance(source_id: str) -> Provenance:
    return Provenance(
        source_system="fake",
        source_id=source_id,
        source_version=None,
        observed_at=NOW,
        ingested_at=NOW,
        parser_version="1.0",
        ingest_run_id="run-1",
        raw_ref=f"raw://{source_id}",
    )


def resource(
    resource_id: str,
    service: str,
    *,
    tenant_id: str = TENANT,
    project_id: str = PROJECT,
    account_id: str = ACCOUNT,
) -> Resource:
    return Resource(
        resource_id=resource_id,
        tenant_id=tenant_id,
        project_id=project_id,
        provider="fake",
        account_id=account_id,
        region="europe-west2",
        service=service,
        resource_type=f"{service}.type",
        native_id=resource_id,
        name=resource_id,
        tags={},
        facts={},
        provenance=(provenance(resource_id),),
        status=FactStatus.OBSERVED,
    )


def cost(
    cost_id: str,
    service: str,
    *,
    period_start: datetime = NOW,
    period_end: datetime = NOW + timedelta(days=1),
) -> CostRecord:
    return CostRecord(
        cost_id=cost_id,
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="fake",
        account_id=ACCOUNT,
        service=service,
        region="europe-west2",
        period_start=period_start,
        period_end=period_end,
        currency="GBP",
        amount_minor=100,
        tags={},
        provenance=provenance(cost_id),
    )


def finding(
    finding_id: str,
    control_id: str,
    *,
    tenant_id: str = TENANT,
    project_id: str = PROJECT,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        tenant_id=tenant_id,
        project_id=project_id,
        control_id=control_id,
        control_version="1.0",
        severity="HIGH",
        affected_resource_id=None,
        affected_workload_id=None,
        outcome=Outcome.PASS,
        evidence_refs=(),
        remediation=None,
        source="fake",
        status="OBSERVED",
    )


def make_adapter(**overrides: object) -> FakeProviderAdapter:
    values: dict[str, object] = {
        "resources": (
            resource("res-3", "storage"),
            resource("res-1", "compute"),
            resource("res-2", "compute"),
            resource("res-4", "database"),
            resource("res-5", "compute"),
            resource("res-other", "compute", tenant_id="tenant-2"),
        ),
        "cost_records": (
            cost("cost-2", "compute"),
            cost("cost-1", "storage"),
            cost(
                "cost-old",
                "compute",
                period_start=NOW - timedelta(days=10),
                period_end=NOW - timedelta(days=9),
            ),
        ),
        "findings": (
            finding("finding-3", "CIS-1.2"),
            finding("finding-1", "CIS-1.1"),
            finding("finding-2", "CIS-1.1"),
            finding("finding-other", "CIS-1.1", tenant_id="tenant-2"),
        ),
        "observed_at": NOW,
    }
    values.update(overrides)
    return FakeProviderAdapter(**values)  # type: ignore[arg-type]


def test_fake_adapter_satisfies_the_full_provider_contract() -> None:
    counts = run_provider_contract(
        make_adapter(),
        inventory=INVENTORY_REQUEST,
        billing=BILLING_REQUEST,
        posture=POSTURE_REQUEST,
    )
    assert counts == {"inventory": 5, "billing": 2, "posture": 3}


def test_descriptor_is_read_only_and_advertises_capabilities() -> None:
    descriptor = make_adapter().descriptor
    assert descriptor.read_only
    assert descriptor.capabilities == frozenset(
        {
            ProviderCapability.INVENTORY,
            ProviderCapability.BILLING,
            ProviderCapability.POSTURE,
        }
    )


def test_descriptor_rejects_write_scope_and_missing_identity() -> None:
    with pytest.raises(ValidationError):
        ProviderDescriptor(
            provider="fake",
            display_name="Fake",
            capabilities=frozenset({ProviderCapability.INVENTORY}),
            read_only=False,
        )
    with pytest.raises(ValidationError):
        ProviderDescriptor(
            provider="",
            display_name="Fake",
            capabilities=frozenset({ProviderCapability.INVENTORY}),
        )
    with pytest.raises(ValidationError):
        ProviderDescriptor(
            provider="fake",
            display_name="Fake",
            capabilities=frozenset(),
        )


def test_fake_adapter_does_not_leak_across_tenants() -> None:
    adapter = make_adapter()
    other = ProviderConnection(
        connection_id="conn-2",
        tenant_id="tenant-2",
        project_id="project-2",
        provider="fake",
        account_id="account-2",
        credential_ref="secret://fake/conn-2",
    )
    assert adapter.read_inventory(InventoryRequest(connection=other)).resources == ()
    assert (
        adapter.read_billing(
            BillingRequest(
                connection=other,
                period_start=NOW,
                period_end=NOW + timedelta(days=2),
            )
        ).records
        == ()
    )
    assert adapter.scan_posture(PostureRequest(connection=other)).findings == ()


def test_fake_adapter_rejects_a_connection_for_another_provider() -> None:
    other = ProviderConnection(
        connection_id="conn-gcp",
        tenant_id=TENANT,
        project_id=PROJECT,
        provider="gcp",
        account_id=ACCOUNT,
        credential_ref="secret://gcp/conn-1",
    )
    with pytest.raises(ValidationError):
        make_adapter().read_inventory(InventoryRequest(connection=other))


def test_fake_adapter_rejects_invalid_cursors() -> None:
    adapter = make_adapter()
    with pytest.raises(ValidationError):
        adapter.read_inventory(InventoryRequest(connection=CONNECTION, cursor="nope"))
    with pytest.raises(ValidationError):
        adapter.read_inventory(InventoryRequest(connection=CONNECTION, cursor="999"))


def test_fake_adapter_failure_injection_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError):
        make_adapter(fail_inventory=True).read_inventory(INVENTORY_REQUEST)
    with pytest.raises(ProviderUnavailableError):
        make_adapter(fail_billing=True).read_billing(BILLING_REQUEST)
    with pytest.raises(ProviderUnavailableError):
        make_adapter(fail_posture=True).scan_posture(POSTURE_REQUEST)


def test_requests_reject_invalid_paging_and_periods() -> None:
    with pytest.raises(ValidationError):
        InventoryRequest(connection=CONNECTION, page_size=0)
    with pytest.raises(ValidationError):
        InventoryRequest(connection=CONNECTION, cursor=" ")
    with pytest.raises(ValidationError):
        BillingRequest(
            connection=CONNECTION,
            period_start=NOW,
            period_end=NOW,
        )
    with pytest.raises(ValidationError):
        ProviderConnection(
            connection_id="conn-1",
            tenant_id=TENANT,
            project_id=PROJECT,
            provider="fake",
            account_id="",
            credential_ref="secret://fake/conn-1",
        )


def test_contract_suite_detects_a_cross_tenant_leak() -> None:
    class LeakyAdapter:
        @property
        def descriptor(self) -> ProviderDescriptor:
            return ProviderDescriptor(
                provider="fake",
                display_name="Leaky",
                capabilities=frozenset({ProviderCapability.INVENTORY}),
            )

        def read_inventory(self, request: InventoryRequest) -> InventoryPage:
            return InventoryPage(
                resources=(resource("res-other", "compute", tenant_id="tenant-2"),),
                next_cursor=None,
                coverage=CoverageReport(observed_services=("compute",)),
                observed_at=NOW,
            )

    with pytest.raises(AssertionError, match="another tenant"):
        assert_inventory_contract(LeakyAdapter(), INVENTORY_REQUEST)


def test_provider_core_imports_no_cloud_sdk() -> None:
    allowed = {"cairn_adapters", "cairn_contracts", "cairn_kernel"}
    violations: dict[str, set[str]] = {}
    for path in PROVIDER_CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        disallowed = {
            root
            for root in roots
            if root not in sys.stdlib_module_names and root not in allowed
        }
        if disallowed:
            violations[path.name] = disallowed
    assert not violations, f"provider-core imported cloud SDKs: {violations}"
