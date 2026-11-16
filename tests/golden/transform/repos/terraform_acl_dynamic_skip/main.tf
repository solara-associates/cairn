resource "aws_s3_bucket" "templated" {
  bucket = "cairn-golden-templated"

  dynamic "grant" {
    for_each = var.grants
    content {
      acl = each.value.acl
    }
  }
}
