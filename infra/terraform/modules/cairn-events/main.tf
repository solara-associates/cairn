# Pub/Sub topics, subscriptions, dead-letter and retry policy.
# Spec §13.3 "cairn-events".

resource "google_pubsub_topic" "topic" {
  for_each = var.topics

  project = var.project_id
  name    = "cairn-${var.environment}-${each.key}"
  labels  = var.labels

  # checkov:skip=CKV_GCP_83: CMEK on Pub/Sub topics is deferred, same decision
  # as the BigQuery datasets in cairn-data — tracked as outstanding in README.md.
}

resource "google_pubsub_topic" "dead_letter" {
  for_each = var.topics

  project = var.project_id
  name    = "cairn-${var.environment}-${each.key}-dlq"
  labels  = var.labels

  # checkov:skip=CKV_GCP_83: see cairn_pubsub_topic.topic above.
}

locals {
  # Flatten {topic => [subscribers]} into one entry per (topic, subscriber) pair.
  subscriptions = merge([
    for topic, cfg in var.topics : {
      for subscriber in cfg.subscribers : "${topic}/${subscriber}" => {
        topic                 = topic
        subscriber            = subscriber
        ack_deadline_seconds  = cfg.ack_deadline_seconds
        max_delivery_attempts = cfg.max_delivery_attempts
      }
    }
  ]...)
}

resource "google_pubsub_subscription" "subscription" {
  for_each = local.subscriptions

  project              = var.project_id
  name                 = "cairn-${var.environment}-${each.value.topic}-${each.value.subscriber}"
  topic                = google_pubsub_topic.topic[each.value.topic].id
  ack_deadline_seconds = each.value.ack_deadline_seconds

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter[each.value.topic].id
    max_delivery_attempts = each.value.max_delivery_attempts
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}
