resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = "${var.app_name}-db"
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_15"

  deletion_protection = false

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    edition           = "ENTERPRISE"

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled    = true
      private_network = null
    }

    database_flags {
      name  = "max_connections"
      value = "50"
    }
  }

  depends_on = [google_project_service.apis["sqladmin.googleapis.com"]]
}

resource "google_sql_database" "app" {
  name     = "opportunity_radar"
  instance = google_sql_database_instance.main.name
  project  = var.project_id
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
  project  = var.project_id
}
