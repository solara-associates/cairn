# Workload Identity service accounts and least-privilege project role bindings.
# Spec §13.3 "cairn-iam": service accounts, WIF, least-privilege roles, KMS IAM.
# KMS key-level IAM (decrypt/sign on the evidence key) is granted in cairn-evidence,
# which already owns the key resource; this module only creates the identities.

resource "google_service_account" "workload" {
  for_each = var.workload_service_accounts

  project      = var.project_id
  account_id   = "${each.key}-${var.environment}"
  display_name = "CAIRN ${each.key} (${var.environment})"
}

locals {
  # Flatten {workload => [roles]} into one {workload/role => {workload, role}}
  # map so each (service account, role) pair becomes its own resource instance.
  role_bindings = merge([
    for workload, roles in var.workload_service_accounts : {
      for role in roles : "${workload}/${role}" => {
        workload = workload
        role     = role
      }
    }
  ]...)
}

resource "google_project_iam_member" "workload_roles" {
  for_each = local.role_bindings

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.workload].email}"
}
