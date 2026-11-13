variable "project_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "topics" {
  description = <<-EOT
    Spec §13.1 / §13.3: "cairn.* topics and subscriptions". Key is the topic
    name suffix (e.g. "estate.changed"); value is the list of subscriber names
    that each get their own pull subscription with a dead-letter policy and
    bounded retry — matching the spec §16.0 gate on duplicate delivery and
    dead-letter replay semantics.
  EOT
  type = map(object({
    subscribers           = list(string)
    ack_deadline_seconds  = number
    max_delivery_attempts = number
  }))
}

variable "labels" {
  type    = map(string)
  default = {}
}
