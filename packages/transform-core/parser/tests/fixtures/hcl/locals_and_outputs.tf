locals {
  common_tags = {
    Project = var.project_name
    Managed = "cairn"
  }
  replica_names = ["a", "b", "c"]
}

output "bucket_name" {
  value = aws_s3_bucket.artifacts.bucket
}
