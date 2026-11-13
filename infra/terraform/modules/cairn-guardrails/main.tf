# Org policies, budgets, spend caps, Cloud Armor.
# Spec §13.3 "cairn-guardrails".

resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        allowed_values = [for loc in var.allowed_resource_locations : "in:${loc}-locations"]
      }
    }
  }
}

resource "google_billing_budget" "monthly_cap" {
  billing_account = var.billing_account_id
  display_name    = "cairn-${var.environment}-monthly-cap"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.monthly_budget_amount_units)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }

  threshold_rules {
    threshold_percent = 0.9
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = var.notification_channel_ids
  }
}

resource "google_compute_security_policy" "edge" {
  project     = var.project_id
  name        = "cairn-${var.environment}-edge"
  description = "Cloud Armor policy fronting cairn-console and any internet-facing LB."

  rule {
    action   = "deny(403)"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "default deny"
  }

  rule {
    action   = "deny(403)"
    priority = 100
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('cve-canary')"
      }
    }
    description = "block CVE-2021-44228 (log4jshell) probe patterns"
  }

  rule {
    action   = "allow"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["0.0.0.0/0"]
      }
    }
    description = "placeholder allow rule; narrow before use in staging/prod"
  }
}
