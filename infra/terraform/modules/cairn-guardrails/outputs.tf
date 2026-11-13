output "security_policy_id" {
  value = google_compute_security_policy.edge.id
}

output "budget_name" {
  value = google_billing_budget.monthly_cap.name
}
