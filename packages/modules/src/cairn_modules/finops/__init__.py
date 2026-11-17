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
from cairn_modules.finops.pricing import InMemoryPriceList
from cairn_modules.finops.remediation_policy import (
    CLASS_C_GRADES,
    MUTATION_CLASS_BY_GRADE,
    RemediationAction,
    RemediationGrade,
    authorize_remediation,
    mutation_class_for_grade,
    tier_for_grade,
)
from cairn_modules.finops.seed import load_price_list_release
from cairn_modules.finops.tco import TcoAssumptions, TcoResult, compute_tco

__all__ = [
    "CLASS_C_GRADES",
    "MUTATION_CLASS_BY_GRADE",
    "BillingLineItem",
    "CostBaseline",
    "InMemoryPriceList",
    "RemediationAction",
    "RemediationGrade",
    "TcoAssumptions",
    "TcoResult",
    "authorize_remediation",
    "build_baseline",
    "build_baselines",
    "compute_tco",
    "import_cost_records",
    "load_price_list_release",
    "mutation_class_for_grade",
    "tier_for_grade",
    "to_cost_record",
]
