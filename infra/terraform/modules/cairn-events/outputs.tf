output "topic_ids" {
  value = { for k, t in google_pubsub_topic.topic : k => t.id }
}

output "subscription_ids" {
  value = { for k, s in google_pubsub_subscription.subscription : k => s.id }
}
