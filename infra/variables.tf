variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "europe-west1"
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "opportunity-radar"
}

variable "db_tier" {
  description = "Cloud SQL instance tier"
  type        = string
  default     = "db-f1-micro"
}

variable "smtp_host" {
  description = "SMTP server host"
  type        = string
  default     = ""
}

variable "smtp_user" {
  description = "SMTP username"
  type        = string
  default     = ""
}

variable "smtp_password" {
  description = "SMTP password"
  type        = string
  default     = ""
  sensitive   = true
}

variable "scheduler_cron" {
  description = "Cloud Scheduler cron expression for periodic pipeline runs"
  type        = string
  default     = "0 2 * * 1"
}
