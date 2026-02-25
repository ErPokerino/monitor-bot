resource "google_service_account" "cloudbuild" {
  account_id   = "or-cloudbuild"
  display_name = "Opportunity Radar - Cloud Build"
  project      = var.project_id
}

locals {
  cloudbuild_roles = [
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/logging.logWriter",
  ]
}

resource "google_project_iam_member" "cloudbuild" {
  for_each = toset(local.cloudbuild_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_cloudbuild_trigger" "deploy" {
  name            = "${var.app_name}-deploy"
  project         = var.project_id
  location        = var.region
  service_account = google_service_account.cloudbuild.id

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

  depends_on = [
    google_project_service.apis["cloudbuild.googleapis.com"],
    google_project_iam_member.cloudbuild,
  ]
}
