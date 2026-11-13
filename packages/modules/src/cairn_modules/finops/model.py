"""R1-11: a provider-agnostic billing line item, prior to canonicalization.

A provider's billing adapter (e.g. ``cairn_adapters.provider_gcp.billing``)
parses its own export format and produces these; ``importer.py`` turns a
sequence of them into canonical ``CostRecord``s. Keeping the GCP-specific
export parsing in the adapter and the canonicalization rules here keeps the
business logic -- currency, period, tags, provenance -- out of the adapter
(ADR A5.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from cairn_kernel.errors import ValidationError


@dataclass(frozen=True, slots=True)
class BillingLineItem:
    """One billing export row, already shaped but not yet canonical.

    ``source_id`` must be stable and unique for the same underlying export
    row across re-imports (so re-running an import is idempotent at the
    cost-record level); ``raw_ref`` points back at the row for provenance.
    """

    source_id: str
    provider: str
    tenant_id: str
    project_id: str
    account_id: str
    service: str
    region: str
    period_start: datetime
    period_end: datetime
    currency: str
    amount_minor: int
    tags: Mapping[str, str]
    raw_ref: str
    source_version: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source id", self.source_id),
            ("provider", self.provider),
            ("tenant id", self.tenant_id),
            ("project id", self.project_id),
            ("account id", self.account_id),
            ("service", self.service),
            ("region", self.region),
            ("currency", self.currency),
            ("raw ref", self.raw_ref),
        ):
            if not value.strip():
                raise ValidationError(f"billing line item {field_name} is required")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValidationError(
                f"billing line item currency {self.currency!r} must be a 3-letter"
                " uppercase ISO 4217 code"
            )
        if self.period_end <= self.period_start:
            raise ValidationError("billing line item period end must be after period start")
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))


__all__ = ["BillingLineItem"]
