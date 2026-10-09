# ============================================================================
# División 3 (IaC + Workaround): Servicios de Gemini Enterprise por Ambiente
# - APIs del Proyecto (google_project_service)
# - Bucket GCS y Objeto del Corpus Oficial GOES (google_storage_bucket)
# - Data Store Nativo en Vertex AI Search (google_discovery_engine_data_store)
# - Workaround Declarativo (terraform_data + local-exec create/destroy) para
#   recursos v1alpha de Gemini Enterprise (LicenseConfig, UserStore, Documento
#   RAG, Engine APP_TYPE_INTRANET y default_assistant)
# ============================================================================

locals {
  corpus_filepath = "${path.module}/../agents/sv_citizen_assistant/corpus/manual_oficial_tramites_sv.md"
  required_services = [
    "discoveryengine.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
  ]
}

# 1. Asegurar APIs requeridas en el proyecto del ambiente
resource "google_project_service" "ge_apis" {
  for_each           = toset(local.required_services)
  project            = var.ge_project_id
  service            = each.value
  disable_on_destroy = false
}

# 2. Bucket GCS para almacenar el Corpus Oficial de Trámites Ciudadanos (GOES)
resource "google_storage_bucket" "corpus_bucket" {
  name                        = "${var.ge_project_id}-ge-corpus-${lower(var.env)}"
  project                     = var.ge_project_id
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = true

  labels = {
    environment = lower(var.env)
    component   = "ge-rag-corpus"
    agency      = "goes"
  }

  depends_on = [google_project_service.ge_apis]
}

# 3. Objeto GCS con el Manual Oficial de Trámites (RNPN, DGME, SERTRACEN)
resource "google_storage_bucket_object" "manual_tramites_goes" {
  name         = "corpus/manual_oficial_tramites_sv.md"
  bucket       = google_storage_bucket.corpus_bucket.name
  source       = local.corpus_filepath
  content_type = "text/markdown"
}

# 4. Recurso Nativo Terraform: Vertex AI Search Data Store
resource "google_discovery_engine_data_store" "tramites_ds" {
  provider                    = google-beta
  project                     = var.ge_project_id
  location                    = var.ge_location
  data_store_id               = var.ge_data_store_id
  display_name                = "Manual Oficial de Tramites Ciudadanos - GOES"
  industry_vertical           = "GENERIC"
  content_config              = "CONTENT_REQUIRED"
  solution_types              = ["SOLUTION_TYPE_SEARCH"]
  create_advanced_site_search = false

  lifecycle {
    ignore_changes = [
      display_name,
      solution_types,
      content_config,
      industry_vertical,
      document_processing_config,
    ]
  }

  depends_on = [google_project_service.ge_apis]
}

# 5. Workaround Declarativo (terraform_data) para recursos v1alpha de Gemini Enterprise:
#    - Create/Update: Reconcilia LicenseConfig, UserStore, Documento RAG, Engine y default_assistant.
#    - Destroy (when = destroy): Elimina primero los agentes custom, el Engine v1alpha y el
#      documento RAG ANTES de que Terraform destruya google_discovery_engine_data_store.tramites_ds,
#      evitando errores 400 (DataStore in use by Engine).
resource "terraform_data" "gemini_enterprise_engine_and_corpus" {
  triggers_replace = [
    var.ge_project_id,
    var.ge_location,
    var.ge_engine_id,
    google_discovery_engine_data_store.tramites_ds.data_store_id,
    filemd5(local.corpus_filepath),
  ]

  input = {
    project_id    = var.ge_project_id
    location      = var.ge_location
    engine_id     = var.ge_engine_id
    data_store_id = google_discovery_engine_data_store.tramites_ds.data_store_id
    corpus_file   = local.corpus_filepath
  }

  provisioner "local-exec" {
    when    = create
    command = <<-EOT
      python3 "${path.module}/../cli/ensure_ge_infra.py" \
        --project-id "${self.input.project_id}" \
        --location "${self.input.location}" \
        --engine-id "${self.input.engine_id}" \
        --data-store-id "${self.input.data_store_id}" \
        --corpus-file "${self.input.corpus_file}"
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<-EOT
      python3 "${path.module}/../cli/ensure_ge_infra.py" \
        --destroy \
        --project-id "${self.output.project_id}" \
        --location "${self.output.location}" \
        --engine-id "${self.output.engine_id}" \
        --data-store-id "${self.output.data_store_id}"
    EOT
  }

  depends_on = [
    google_discovery_engine_data_store.tramites_ds,
    google_storage_bucket_object.manual_tramites_goes,
  ]
}
