output "service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.main.uri
}

output "cloud_sql_connection" {
  description = "Cloud SQL connection name"
  value       = google_sql_database_instance.main.connection_name
}

output "artifact_registry" {
  description = "Docker image base path"
  value       = local.image_base
}

output "scheduler_job" {
  description = "Cloud Scheduler job name"
  value       = google_cloud_scheduler_job.pipeline.name
}
