output "ge_project_id" {
  value       = var.ge_project_id
  description = "GCP Project ID provisioned by Terraform"
}

output "ge_location" {
  value       = var.ge_location
  description = "Discovery Engine location provisioned by Terraform"
}

output "ge_engine_id" {
  value       = var.ge_engine_id
  description = "Gemini Enterprise Engine ID reconciled by Terraform workaround"
}

output "ge_data_store_id" {
  value       = google_discovery_engine_data_store.tramites_ds.data_store_id
  description = "Vertex AI Search Data Store ID managed natively by Terraform"
}

output "corpus_bucket_uri" {
  value       = "gs://${google_storage_bucket.corpus_bucket.name}/${google_storage_bucket_object.manual_tramites_goes.name}"
  description = "GCS URI of the official GOES procedures corpus markdown"
}
