variable "project_id" {
  description = "The CAIRN control-plane project this custom role is defined in (not the customer's project)."
  type        = string
}

variable "environment" {
  type = string
}
