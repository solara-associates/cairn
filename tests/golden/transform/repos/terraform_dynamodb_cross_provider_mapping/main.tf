resource "aws_dynamodb_table" "sessions" {
  name         = "cairn-demo-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }
}
