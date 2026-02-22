resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = var.app_name
  format        = "DOCKER"
  project       = var.project_id

  depends_on = [google_project_service.apis["artifactregistry.googleapis.com"]]
}

locals {
  image_base = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}/${var.app_name}"
}
