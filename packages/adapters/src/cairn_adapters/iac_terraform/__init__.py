"""R2-07: ``IaCGeneratorPort`` adapters (spec §5.4) -- a real
deterministic Terraform-style HCL plan-preview text emitter and a
deterministic fake for tests. Plan only; no apply; no Terraform binary,
cloud SDK or cloud credential anywhere in this package (ADR-010)."""

from cairn_adapters.iac_terraform.fake import FakeIaCGenerator
from cairn_adapters.iac_terraform.terraform import TerraformHclGenerator

__all__ = ["FakeIaCGenerator", "TerraformHclGenerator"]
