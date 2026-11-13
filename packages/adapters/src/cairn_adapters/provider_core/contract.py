from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from cairn_contracts.estate import CostRecord, Finding, Resource

from cairn_adapters.provider_core.ports import (
    BillingPage,
    BillingRequest,
    CoverageReport,
    InventoryPage,
    InventoryRequest,
    PosturePage,
    PostureRequest,
    ProviderCapability,
    ProviderDescriptor,
)

MAX_PAGES = 10_000

PageT = TypeVar("PageT")
ItemT = TypeVar("ItemT")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _descriptor(adapter: object) -> ProviderDescriptor:
    descriptor = getattr(adapter, "descriptor", None)
    _require(
        isinstance(descriptor, ProviderDescriptor),
        "adapter must expose a ProviderDescriptor",
    )
    _require(descriptor.read_only, "provider-core adapters must be read-only")
    return descriptor


def assert_capability(adapter: object, capability: ProviderCapability) -> None:
    descriptor = _descriptor(adapter)
    _require(
        capability in descriptor.capabilities,
        f"{descriptor.provider} does not advertise {capability.value}",
    )


def _collect_pages(
    page_reader: Callable[[str | None], PageT],
    page_size: int,
    item_reader: Callable[[PageT], tuple[ItemT, ...]],
    next_cursor: Callable[[PageT], str | None],
) -> tuple[ItemT, ...]:
    items: list[ItemT] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        page = page_reader(cursor)
        batch = item_reader(page)
        _require(
            len(batch) <= page_size,
            f"page returned {len(batch)} items for page size {page_size}",
        )
        items.extend(batch)
        cursor = next_cursor(page)
        if cursor is None:
            return tuple(items)
    raise AssertionError("pagination did not terminate")


def _assert_unique(values: list[str], label: str) -> None:
    _require(len(values) == len(set(values)), f"{label} must be unique across pages")


def assert_inventory_contract(
    adapter: object,
    request: InventoryRequest,
    *,
    expected_resource_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    assert_capability(adapter, ProviderCapability.INVENTORY)
    read = adapter.read_inventory  # type: ignore[attr-defined]

    def read_page(cursor: str | None) -> InventoryPage:
        page = read(replace(request, cursor=cursor))
        _require(isinstance(page, InventoryPage), "inventory read must return a page")
        for resource in page.resources:
            _require(isinstance(resource, Resource), "inventory pages hold resources")
            _require(
                resource.tenant_id == request.connection.tenant_id,
                "inventory leaked a resource from another tenant",
            )
            _require(
                resource.project_id == request.connection.project_id,
                "inventory leaked a resource from another project",
            )
            _require(
                resource.account_id == request.connection.account_id,
                "inventory leaked a resource from another account",
            )
            _require(
                not request.services or resource.service in request.services,
                "inventory returned a service that was not requested",
            )
            _require(
                isinstance(page.coverage, CoverageReport),
                "inventory page needs a coverage report",
            )
        return page

    first = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.resources,
        lambda page: page.next_cursor,
    )
    second = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.resources,
        lambda page: page.next_cursor,
    )
    ids = [resource.resource_id for resource in first]
    _assert_unique(ids, "inventory resource ids")
    _require(
        tuple(ids) == tuple(resource.resource_id for resource in second),
        "inventory pagination is not deterministic",
    )
    if expected_resource_ids is not None:
        _require(
            tuple(ids) == expected_resource_ids,
            f"inventory ids {tuple(ids)} do not match {expected_resource_ids}",
        )
    return tuple(ids)


def assert_billing_contract(
    adapter: object,
    request: BillingRequest,
    *,
    expected_cost_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    assert_capability(adapter, ProviderCapability.BILLING)
    read = adapter.read_billing  # type: ignore[attr-defined]

    def read_page(cursor: str | None) -> BillingPage:
        page = read(replace(request, cursor=cursor))
        _require(isinstance(page, BillingPage), "billing read must return a page")
        for record in page.records:
            _require(isinstance(record, CostRecord), "billing pages hold cost records")
            _require(
                record.tenant_id == request.connection.tenant_id,
                "billing leaked a record from another tenant",
            )
            _require(
                record.project_id == request.connection.project_id,
                "billing leaked a record from another project",
            )
            _require(
                record.account_id == request.connection.account_id,
                "billing leaked a record from another account",
            )
            _require(
                record.period_start < request.period_end
                and record.period_end > request.period_start,
                "billing returned a record outside the requested period",
            )
            _require(
                isinstance(page.coverage, CoverageReport),
                "billing page needs a coverage report",
            )
        return page

    first = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.records,
        lambda page: page.next_cursor,
    )
    second = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.records,
        lambda page: page.next_cursor,
    )
    ids = [record.cost_id for record in first]
    _assert_unique(ids, "billing cost ids")
    _require(
        tuple(ids) == tuple(record.cost_id for record in second),
        "billing pagination is not deterministic",
    )
    if expected_cost_ids is not None:
        _require(
            tuple(ids) == expected_cost_ids,
            f"billing ids {tuple(ids)} do not match {expected_cost_ids}",
        )
    return tuple(ids)


def assert_posture_contract(
    adapter: object,
    request: PostureRequest,
    *,
    expected_finding_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    assert_capability(adapter, ProviderCapability.POSTURE)
    scan = adapter.scan_posture  # type: ignore[attr-defined]

    def read_page(cursor: str | None) -> PosturePage:
        page = scan(replace(request, cursor=cursor))
        _require(isinstance(page, PosturePage), "posture scan must return a page")
        _require(bool(page.scanner_version.strip()), "posture needs a scanner version")
        for finding in page.findings:
            _require(isinstance(finding, Finding), "posture pages hold findings")
            _require(
                finding.tenant_id == request.connection.tenant_id,
                "posture leaked a finding from another tenant",
            )
            _require(
                finding.project_id == request.connection.project_id,
                "posture leaked a finding from another project",
            )
            _require(
                not request.controls or finding.control_id in request.controls,
                "posture returned a control that was not requested",
            )
            _require(
                isinstance(page.coverage, CoverageReport),
                "posture page needs a coverage report",
            )
        return page

    first = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.findings,
        lambda page: page.next_cursor,
    )
    second = _collect_pages(
        read_page,
        request.page_size,
        lambda page: page.findings,
        lambda page: page.next_cursor,
    )
    ids = [finding.finding_id for finding in first]
    _assert_unique(ids, "posture finding ids")
    _require(
        tuple(ids) == tuple(finding.finding_id for finding in second),
        "posture pagination is not deterministic",
    )
    if expected_finding_ids is not None:
        _require(
            tuple(ids) == expected_finding_ids,
            f"posture ids {tuple(ids)} do not match {expected_finding_ids}",
        )
    return tuple(ids)


def run_provider_contract(
    adapter: object,
    *,
    inventory: InventoryRequest | None = None,
    billing: BillingRequest | None = None,
    posture: PostureRequest | None = None,
) -> dict[str, int]:
    descriptor = _descriptor(adapter)
    counts: dict[str, int] = {}
    for capability, request, run in (
        (ProviderCapability.INVENTORY, inventory, assert_inventory_contract),
        (ProviderCapability.BILLING, billing, assert_billing_contract),
        (ProviderCapability.POSTURE, posture, assert_posture_contract),
    ):
        if capability not in descriptor.capabilities:
            continue
        _require(request is not None, f"{capability.value} adapter needs a request")
        counts[capability.value.lower()] = len(run(adapter, request))  # type: ignore[arg-type]
    return counts
