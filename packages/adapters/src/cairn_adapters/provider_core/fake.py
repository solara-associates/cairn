from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from cairn_contracts.estate import CostRecord, Finding, Resource
from cairn_kernel.errors import ProviderUnavailableError, ValidationError

from cairn_adapters.provider_core.ports import (
    BillingPage,
    BillingRequest,
    CoverageReport,
    InventoryPage,
    InventoryRequest,
    PosturePage,
    PostureRequest,
    ProviderCapability,
    ProviderConnection,
    ProviderDescriptor,
)

T = TypeVar("T")


def _offset(cursor: str | None, total: int) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise ValidationError("provider cursor is not valid") from exc
    if offset < 0 or offset > total:
        raise ValidationError("provider cursor is out of range")
    return offset


def _page(
    items: Sequence[T],
    cursor: str | None,
    page_size: int,
) -> tuple[tuple[T, ...], str | None]:
    offset = _offset(cursor, len(items))
    page = tuple(items[offset : offset + page_size])
    end = offset + len(page)
    next_cursor = None if end >= len(items) else str(end)
    return page, next_cursor


class FakeProviderAdapter:
    """Deterministic read-only provider used by the contract suite and tests."""

    def __init__(
        self,
        *,
        resources: Sequence[Resource] = (),
        cost_records: Sequence[CostRecord] = (),
        findings: Sequence[Finding] = (),
        provider: str = "fake",
        observed_at: datetime | None = None,
        fail_inventory: bool = False,
        fail_billing: bool = False,
        fail_posture: bool = False,
    ) -> None:
        self._provider = provider
        self._observed_at = observed_at or datetime.now(UTC)
        self._resources = tuple(sorted(resources, key=lambda item: item.resource_id))
        self._cost_records = tuple(
            sorted(cost_records, key=lambda item: item.cost_id)
        )
        self._findings = tuple(sorted(findings, key=lambda item: item.finding_id))
        self.fail_inventory = fail_inventory
        self.fail_billing = fail_billing
        self.fail_posture = fail_posture

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider=self._provider,
            display_name="Fake provider",
            capabilities=frozenset(
                {
                    ProviderCapability.INVENTORY,
                    ProviderCapability.BILLING,
                    ProviderCapability.POSTURE,
                }
            ),
        )

    def read_inventory(self, request: InventoryRequest) -> InventoryPage:
        if self.fail_inventory:
            raise ProviderUnavailableError("fake inventory source is unavailable")
        connection = self._checked_connection(request.connection)
        services = set(request.services)
        matching = tuple(
            resource
            for resource in self._resources
            if _matches(resource, connection)
            and (not services or resource.service in services)
        )
        page, next_cursor = _page(matching, request.cursor, request.page_size)
        observed = tuple(sorted({resource.service for resource in matching}))
        skipped = tuple(
            sorted(service for service in services if service not in observed)
        )
        return InventoryPage(
            resources=page,
            next_cursor=next_cursor,
            coverage=CoverageReport(
                observed_services=observed,
                skipped_services=skipped,
            ),
            observed_at=self._observed_at,
        )

    def read_billing(self, request: BillingRequest) -> BillingPage:
        if self.fail_billing:
            raise ProviderUnavailableError("fake billing source is unavailable")
        connection = self._checked_connection(request.connection)
        matching = tuple(
            record
            for record in self._cost_records
            if _matches(record, connection)
            and record.provider == connection.provider
            and record.period_start < request.period_end
            and record.period_end > request.period_start
        )
        page, next_cursor = _page(matching, request.cursor, request.page_size)
        observed = tuple(sorted({record.service for record in matching}))
        return BillingPage(
            records=page,
            next_cursor=next_cursor,
            coverage=CoverageReport(observed_services=observed),
            observed_at=self._observed_at,
        )

    def scan_posture(self, request: PostureRequest) -> PosturePage:
        if self.fail_posture:
            raise ProviderUnavailableError("fake posture scanner is unavailable")
        connection = self._checked_connection(request.connection)
        controls = set(request.controls)
        matching = tuple(
            finding
            for finding in self._findings
            if finding.tenant_id == connection.tenant_id
            and finding.project_id == connection.project_id
            and (not controls or finding.control_id in controls)
        )
        page, next_cursor = _page(matching, request.cursor, request.page_size)
        observed = tuple(sorted({finding.control_id for finding in matching}))
        skipped = tuple(
            sorted(control for control in controls if control not in observed)
        )
        return PosturePage(
            findings=page,
            scanner_version="fake-scanner-1.0",
            next_cursor=next_cursor,
            coverage=CoverageReport(
                observed_services=observed,
                skipped_services=skipped,
            ),
            observed_at=self._observed_at,
        )

    def _checked_connection(self, connection: ProviderConnection) -> ProviderConnection:
        if connection.provider != self._provider:
            raise ValidationError(
                f"connection provider {connection.provider} does not match {self._provider}"
            )
        return connection


def _matches(item: Resource | CostRecord, connection: ProviderConnection) -> bool:
    return (
        item.tenant_id == connection.tenant_id
        and item.project_id == connection.project_id
        and item.account_id == connection.account_id
    )
