# Customer onboarding role definition for GCP read-only connections.
# Spec §13.3 "cairn-connections": customer onboarding roles for GCP read-only;
# separate execution roles only in R4+ after the kernel execution gate is
# proven (ADR-010). This module defines the role grantable in a *customer's*
# project; it does not grant it anywhere itself — granting happens when a
# customer connects (R1-02), not at infrastructure-provisioning time.

resource "google_project_iam_custom_role" "read_only_connection" {
  project     = var.project_id
  role_id     = "cairnReadOnlyConnection${title(var.environment)}"
  title       = "CAIRN read-only connection (${var.environment})"
  description = "Granted in a customer's GCP project when they connect it to CAIRN for assessment. Read-only: no write, execute, or delete permissions. No execution role exists before R4 (ADR-010)."

  permissions = [
    "resourcemanager.projects.get",
    "resourcemanager.projects.list",
    "compute.instances.list",
    "compute.disks.list",
    "compute.networks.list",
    "cloudasset.assets.listResource",
    "billing.accounts.get",
    "billing.resourceAssociations.list",
    "monitoring.timeSeries.list",
  ]
}
