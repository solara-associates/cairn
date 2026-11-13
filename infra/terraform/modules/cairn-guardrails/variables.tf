variable "project_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "billing_account_id" {
  description = "Billing account to attach the budget to."
  type        = string
}

variable "monthly_budget_amount_units" {
  description = "Monthly spend cap in whole currency units (spec §13.3 'budgets, spend caps')."
  type        = number
}

variable "budget_currency_code" {
  type    = string
  default = "GBP"
}

variable "allowed_resource_locations" {
  description = "Org-policy resource-location restriction, e.g. [\"europe-west2\"], enforcing the UK residency matrix (spec §13.6)."
  type        = list(string)
}

variable "notification_channel_ids" {
  description = "Monitoring notification channels (from cairn-observability) that receive budget alerts."
  type        = list(string)
  default     = []
}
