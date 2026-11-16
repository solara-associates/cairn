resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-demo-artifacts"
  tags = {
    Team = "platform"
  }
}

resource "aws_iam_role" "worker" {
  name = "cairn-worker-role"
  assume_role_policy = "{}"
}
