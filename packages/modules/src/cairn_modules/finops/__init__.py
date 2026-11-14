"""CAIRN cairn_modules.finops.

R1-11: canonical cost records. ``model.BillingLineItem`` is the
provider-agnostic shape a billing adapter produces from its own export
format; ``importer.import_cost_records`` turns a batch of those into
canonical ``cairn_contracts.estate.CostRecord``s, carrying currency,
billing period, resource tags, and provenance on every record.
"""

from cairn_modules.finops.baseline import CostBaseline, build_baseline, build_baselines
from cairn_modules.finops.importer import import_cost_records, to_cost_record
from cairn_modules.finops.model import BillingLineItem

__all__ = [
    "BillingLineItem",
    "CostBaseline",
    "build_baseline",
    "build_baselines",
    "import_cost_records",
    "to_cost_record",
]
