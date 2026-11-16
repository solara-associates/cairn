resource "aws_s3_bucket" "logs" {
  bucket = "cairn-golden-logs"
}

resource "aws_s3_bucket_acl" "logs" {
  bucket = aws_s3_bucket.logs.id
  acl    = "log-delivery-write"
}
