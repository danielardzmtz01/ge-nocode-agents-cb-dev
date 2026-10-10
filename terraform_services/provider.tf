terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0.0"
    }
  }
}

provider "google" {
  project               = var.ge_project_id
  billing_project       = var.ge_project_id
  user_project_override = true
}

provider "google-beta" {
  project               = var.ge_project_id
  billing_project       = var.ge_project_id
  user_project_override = true
}
