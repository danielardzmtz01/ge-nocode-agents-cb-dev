variable "env" {
  description = "Environment identifier injected via spec_variables.auto.tfvars (dev, stg, prd)"
  type        = string
}

variable "ge_project_id" {
  description = "Target Google Cloud Project ID for this environment (injected via spec_variables.auto.tfvars)"
  type        = string
}

variable "ge_location" {
  description = "Discovery Engine / Gemini Enterprise location (injected via spec_variables.auto.tfvars)"
  type        = string
}

variable "ge_engine_id" {
  description = "Gemini Enterprise Engine (App) ID (injected via spec_variables.auto.tfvars)"
  type        = string
}

variable "ge_data_store_id" {
  description = "Vertex AI Search Data Store ID for RAG grounding (injected via spec_variables.auto.tfvars)"
  type        = string
}
