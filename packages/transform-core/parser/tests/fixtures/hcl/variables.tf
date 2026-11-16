variable "project_name" {
  type    = string
  default = "cairn-demo"
}

variable "replica_count" {
  type    = number
  default = 3
}

variable "feature_flags" {
  type    = list(string)
  default = ["flag-a", "flag-b"]
}
