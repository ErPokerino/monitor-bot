resource "google_cloud_scheduler_job" "pipeline" {
  name      = "${var.app_name}-weekly"
  project   = var.project_id
  region    = var.region
  schedule  = var.scheduler_cron
  time_zone = "Europe/Rome"

  http_target {
    uri         = "${google_cloud_run_v2_service.main.uri}/api/runs/start"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = google_cloud_run_v2_service.main.uri
    }
  }

  retry_config {
    retry_count = 1
  }

  lifecycle {
    ignore_changes = [schedule]
  }

  depends_on = [google_project_service.apis["cloudscheduler.googleapis.com"]]
}
