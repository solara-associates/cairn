resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-golden-artifacts"
  acl    = "private"
}
