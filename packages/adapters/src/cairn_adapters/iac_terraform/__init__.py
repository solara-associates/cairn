"""R2-07: ``IaCGeneratorPort`` adapters (spec §5.4) -- a real
deterministic Terraform-style HCL plan-preview text emitter and a
deterministic fake for tests. Plan only; no apply; no Terraform binary,
cloud SDK or cloud credential anywhere in this package (ADR-010).

787 (R4-03a) adds ``plan_orchestration``: Terraform plan orchestration and
diff capture on top of this package's plan preview and 784's
``ProviderExecutionPort`` contract, still plan-only, still no cloud."""

from cairn_adapters.iac_terraform.fake import FakeIaCGenerator
from cairn_adapters.iac_terraform.plan_orchestration import (
    TERRAFORM_PLAN_OPERATION,
    PlanDiffAction,
    TerraformPlanDiffEntry,
    TerraformPlanRevisionPayload,
    orchestrate_terraform_plan,
)
from cairn_adapters.iac_terraform.terraform import TerraformHclGenerator

__all__ = [
    "TERRAFORM_PLAN_OPERATION",
    "FakeIaCGenerator",
    "PlanDiffAction",
    "TerraformHclGenerator",
    "TerraformPlanDiffEntry",
    "TerraformPlanRevisionPayload",
    "orchestrate_terraform_plan",
]
