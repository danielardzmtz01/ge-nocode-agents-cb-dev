# ============================================================================
# División 1 (IaC): Proyectos GCP por Ambiente (Track A: GHA y Track B: Cloud Build),
# APIs, Service Accounts de CI/CD, IAM y Secret Manager
# ============================================================================

locals {
  env_projects = {
    gha = {
      project_id = "goes-ge-gha-${lower(var.env)}"
      name       = "GOES GE GitHub Actions ${upper(var.env)}"
      track      = "github-actions"
    }
    cb = {
      project_id = "goes-ge-cb-${lower(var.env)}"
      name       = "GOES GE Cloud Build ${upper(var.env)}"
      track      = "cloud-build"
    }
  }

  project_api_pairs = flatten([
    for track_key, prj in local.env_projects : [
      for api in var.activate_apis : {
        key        = "${track_key}-${api}"
        project_id = prj.project_id
        api        = api
      }
    ]
  ])

  cicd_roles = [
    "roles/discoveryengine.admin",
    "roles/discoveryengine.user",
    "roles/discoveryengine.agentspaceUser",
    "roles/aiplatform.user",
    "roles/storage.admin",
    "roles/secretmanager.secretAccessor",
    "roles/cloudbuild.builds.editor",
    "roles/serviceusage.serviceUsageAdmin",
  ]

  project_role_pairs = flatten([
    for track_key, prj in local.env_projects : [
      for role in local.cicd_roles : {
        key        = "${track_key}-${role}"
        project_id = prj.project_id
        role       = role
        track_key  = track_key
      }
    ]
  ])
}

# 1. Proyectos GCP dentro del folder GOES
resource "google_project" "goes_env_projects" {
  for_each        = local.env_projects
  name            = each.value.name
  project_id      = each.value.project_id
  folder_id       = local.resolved_folder_id
  billing_account = var.billing_account

  labels = {
    environment = lower(var.env)
    orchestrator = each.value.track
    initiative  = "goes-nocode-agents"
  }
}

# 2. Habilitación declarativa de APIs requeridas
resource "google_project_service" "enabled_apis" {
  for_each           = { for item in local.project_api_pairs : item.key => item }
  project            = google_project.goes_env_projects[split("-", each.key)[0]].project_id
  service            = each.value.api
  disable_on_destroy = false
}

# 3. Service Account dedicada para el Runner de CI/CD en cada proyecto
resource "google_service_account" "cicd_runner" {
  for_each     = local.env_projects
  project      = google_project.goes_env_projects[each.key].project_id
  account_id   = "ge-cicd-runner"
  display_name = "Gemini Enterprise No-Code CI/CD Runner (${upper(var.env)})"
  depends_on   = [google_project_service.enabled_apis]
}

# 4. Asignación de roles IAM de mínimo privilegio al Service Account
resource "google_project_iam_member" "cicd_runner_roles" {
  for_each = { for item in local.project_role_pairs : item.key => item }
  project  = each.value.project_id
  role     = each.value.role
  member   = "serviceAccount:${google_service_account.cicd_runner[each.value.track_key].email}"
}

# 5. Workload Identity Federation (Keyless OIDC para GitHub Actions)
resource "google_iam_workload_identity_pool" "github_pool" {
  project                   = google_project.goes_env_projects["gha"].project_id
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Keyless OIDC Federation for GitHub Actions CI/CD"
  depends_on                = [google_project_service.enabled_apis]
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  project                            = google_project.goes_env_projects["gha"].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  attribute_condition = "assertion.repository_owner == 'danielardzmtz01'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "gha_wif_binding" {
  service_account_id = google_service_account.cicd_runner["gha"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_pool.name}/attribute.repository/danielardzmtz01/ge-nocode-agents-${lower(var.env)}"
}

# 6. Secreto en Secret Manager (para Cloud Build: github-pat para promover entre repos)
resource "google_secret_manager_secret" "github_pat" {
  project   = google_project.goes_env_projects["cb"].project_id
  secret_id = "github-pat"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled_apis]
}

output "gha_project_id" {
  value       = google_project.goes_env_projects["gha"].project_id
  description = "Project ID for GitHub Actions track in current environment"
}

output "gha_wif_provider" {
  value       = google_iam_workload_identity_pool_provider.github_provider.name
  description = "Workload Identity Provider resource name for GitHub Actions"
}

output "gha_service_account" {
  value       = google_service_account.cicd_runner["gha"].email
  description = "Dedicated CI/CD Service Account email for GitHub Actions"
}

output "cb_project_id" {
  value       = google_project.goes_env_projects["cb"].project_id
  description = "Project ID for Cloud Build track in current environment"
}

output "cb_service_account" {
  value       = google_service_account.cicd_runner["cb"].email
  description = "Dedicated CI/CD Service Account email for Cloud Build"
}
