output "access_log_bucket_name" {
  value = google_storage_bucket.access_logs.name
}

output "log_sink_writer_identity" {
  description = "Grant this identity write access on log_sink_destination."
  value       = google_logging_project_sink.cairn.writer_identity
}

output "notification_channel_id" {
  value = google_monitoring_notification_channel.oncall.id
}
