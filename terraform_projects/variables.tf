variable "org_id" {
  description = "Google Cloud Organization ID"
  type        = string
}

variable "billing_account" {
  description = "Billing Account ID to link GOES projects"
  type        = string
}

variable "terraform_project" {
  description = "Centralized project where Terraform state bucket lives (e.g. drm-tfproject-000)"
  type        = string
}

variable "goes_folder_id" {
  description = "Existing GOES Folder ID under organization (folders/402619928367) or empty to create"
  type        = string
  default     = "folders/402619928367"
}

variable "env" {
  description = "Target environment injected via spec_variables.auto.tfvars (dev, stg, prd)"
  type        = string
}

variable "activate_apis" {
  description = "Core GCP APIs enabled across GOES Gemini Enterprise projects"
  type        = list(string)
  default = [
    "discoveryengine.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ]
}
