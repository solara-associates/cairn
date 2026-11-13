from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from cairn_contracts.estate import CostRecord, Finding, Resource
from cairn_kernel.errors import ValidationError


class ProviderCapability(str, Enum):
    INVENTORY = "INVENTORY"
    BILLING = "BILLING"
    POSTURE = "POSTURE"


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider: str
    display_name: str
    capabilities: frozenset[ProviderCapability]
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValidationError("provider name is required")
        if not self.display_name.strip():
            raise ValidationError("provider display name is required")
        if not self.capabilities:
            raise ValidationError("provider must declare at least one capability")
        if not self.read_only:
            raise ValidationError("provider-core contracts are read-only before R4")


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    connection_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    credential_ref: str

    def __post_init__(self) -> None:
        for field, value in (
            ("connection id", self.connection_id),
            ("tenant id", self.tenant_id),
            ("project id", self.project_id),
            ("provider", self.provider),
            ("account id", self.account_id),
            ("credential reference", self.credential_ref),
        ):
            if not value.strip():
                raise ValidationError(f"provider connection {field} is required")


@dataclass(frozen=True, slots=True)
class CoverageReport:
    observed_services: tuple[str, ...] = ()
    skipped_services: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, values in (
            ("observed services", self.observed_services),
            ("skipped services", self.skipped_services),
            ("errors", self.errors),
        ):
            if any(not value.strip() for value in values):
                raise ValidationError(f"coverage {name} must not contain blanks")

    @property
    def complete(self) -> bool:
        return not self.skipped_services and not self.errors


@dataclass(frozen=True, slots=True)
class InventoryRequest:
    connection: ProviderConnection
    cursor: str | None = None
    page_size: int = 100
    services: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_page(self.cursor, self.page_size)
        if any(not service.strip() for service in self.services):
            raise ValidationError("inventory services must not contain blanks")


@dataclass(frozen=True, slots=True)
class BillingRequest:
    connection: ProviderConnection
    period_start: datetime
    period_end: datetime
    cursor: str | None = None
    page_size: int = 100

    def __post_init__(self) -> None:
        _validate_page(self.cursor, self.page_size)
        if self.period_end <= self.period_start:
            raise ValidationError("billing period end must be after period start")


@dataclass(frozen=True, slots=True)
class PostureRequest:
    connection: ProviderConnection
    cursor: str | None = None
    page_size: int = 100
    controls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_page(self.cursor, self.page_size)
        if any(not control.strip() for control in self.controls):
            raise ValidationError("posture controls must not contain blanks")


def _validate_page(cursor: str | None, page_size: int) -> None:
    if cursor is not None and not cursor.strip():
        raise ValidationError("cursor must not be blank")
    if not 1 <= page_size <= 1000:
        raise ValidationError("page size must be between 1 and 1000")


@dataclass(frozen=True, slots=True)
class InventoryPage:
    resources: tuple[Resource, ...]
    next_cursor: str | None
    coverage: CoverageReport
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class BillingPage:
    records: tuple[CostRecord, ...]
    next_cursor: str | None
    coverage: CoverageReport
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PosturePage:
    findings: tuple[Finding, ...]
    scanner_version: str
    next_cursor: str | None
    coverage: CoverageReport
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.scanner_version.strip():
            raise ValidationError("posture scanner version is required")


class InventorySourcePort(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def read_inventory(self, request: InventoryRequest) -> InventoryPage: ...


class BillingSourcePort(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def read_billing(self, request: BillingRequest) -> BillingPage: ...


class PostureScannerPort(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def scan_posture(self, request: PostureRequest) -> PosturePage: ...
