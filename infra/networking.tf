resource "google_vpc_access_connector" "main" {
  name          = "${var.app_name}-vpc"
  project       = var.project_id
  region        = var.region
  ip_cidr_range = "10.8.0.0/28"
  network       = "default"

  depends_on = [google_project_service.apis["vpcaccess.googleapis.com"]]
}
