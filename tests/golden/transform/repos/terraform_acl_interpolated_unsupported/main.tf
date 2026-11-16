resource "aws_s3_bucket" "interpolated" {
  bucket = "cairn-golden-interpolated"
  acl    = "${var.environment}-public-read"
}
