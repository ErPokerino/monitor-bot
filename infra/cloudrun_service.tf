resource "google_cloud_run_v2_service" "main" {
  name     = var.app_name
  project  = var.project_id
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = 1
      max_instance_count = 2
    }

    timeout = "300s"

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = "${local.image_base}:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "DATABASE_URL"
        value = "postgresql+asyncpg://app:${random_password.db_password.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "GCP_REGION"
        value = var.region
      }

      env {
        name  = "ENV"
        value = "production"
      }

      env {
        name  = "LOG_TO_FILE"
        value = "0"
      }

      env {
        name  = "STATIC_DIR"
        value = "/app/static"
      }

      dynamic "env" {
        for_each = var.smtp_host != "" ? [1] : []
        content {
          name  = "SMTP_HOST"
          value = var.smtp_host
        }
      }

      dynamic "env" {
        for_each = var.smtp_user != "" ? [1] : []
        content {
          name  = "SMTP_USER"
          value = var.smtp_user
        }
      }

      dynamic "env" {
        for_each = var.smtp_password != "" ? [1] : []
        content {
          name = "SMTP_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.smtp_password[0].secret_id
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  depends_on = [
    google_project_service.apis["run.googleapis.com"],
    google_sql_database.app,
    google_sql_user.app,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.main.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
