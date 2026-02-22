# --- SA: Cloud Run Service (API + frontend) ---

resource "google_service_account" "runtime" {
  account_id   = "or-runtime"
  display_name = "Opportunity Radar - Cloud Run Service"
  project      = var.project_id
}

locals {
  runtime_roles = [
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/storage.objectUser",
    "roles/run.developer",
    "roles/aiplatform.user",
    "roles/cloudscheduler.admin",
  ]
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(local.runtime_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}


# --- SA: Cloud Run Job (pipeline) ---

resource "google_service_account" "pipeline" {
  account_id   = "or-pipeline"
  display_name = "Opportunity Radar - Pipeline Job"
  project      = var.project_id
}

locals {
  pipeline_roles = [
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/storage.objectUser",
    "roles/aiplatform.user",
  ]
}

resource "google_project_iam_member" "pipeline" {
  for_each = toset(local.pipeline_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.pipeline.email}"
}


# --- SA: Cloud Scheduler ---

resource "google_service_account" "scheduler" {
  account_id   = "or-scheduler"
  display_name = "Opportunity Radar - Scheduler"
  project      = var.project_id
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.main.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}
