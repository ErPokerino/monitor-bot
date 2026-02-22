resource "google_cloudbuild_trigger" "deploy" {
  name            = "${var.app_name}-deploy"
  project         = var.project_id
  location        = var.region
  service_account = "projects/${var.project_id}/serviceAccounts/${data.google_project.current.number}@cloudbuild.gserviceaccount.com"

  repository_event_config {
    repository = "projects/${var.project_id}/locations/${var.region}/connections/github-connection/repositories/monitor-bot"

    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"

  substitutions = {
    _REGION     = var.region
    _REPO       = google_artifact_registry_repository.main.repository_id
    _SERVICE    = google_cloud_run_v2_service.main.name
    _JOB        = google_cloud_run_v2_job.pipeline.name
    _IMAGE_BASE = local.image_base
  }

  depends_on = [google_project_service.apis["cloudbuild.googleapis.com"]]
}

data "google_project" "current" {
  project_id = var.project_id
}
