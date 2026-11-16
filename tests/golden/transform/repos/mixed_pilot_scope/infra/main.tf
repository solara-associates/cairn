resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-golden-mixed-artifacts"
  acl    = "public-read"
}
