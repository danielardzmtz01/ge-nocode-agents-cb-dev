# Guía Paso a Paso de Replicación para el Gobierno de El Salvador (GOES)

> [!IMPORTANT]
> **Propósito de esta Guía**: Este manual operativo está diseñado para que el equipo de Ingeniería de Plataforma, DevOps e Inteligencia Artificial del **Gobierno de El Salvador (GOES)** pueda **replicar de principio a fin** la arquitectura de **CI/CD In-Place (`dev` $\rightarrow$ `stg` $\rightarrow$ `prd`), Infraestructura como Código (Terraform) y Evaluación Automatizada (`google-adk`) para Agentes No-Code en Gemini Enterprise** dentro de su propia organización de Google Cloud y su propia cuenta u organización de GitHub.

---

## 1. Visión General de lo que se va a Replicar

La arquitectura desacopla el ciclo de vida en **3 ambientes aislados (`DEV`, `STG`, `PRD`)** donde **todos los repositorios comparten exactamente el mismo código fuente** sin ningún identificador quemado (*zero hardcoded IDs*). Puedes elegir cualquiera de los dos motores de orquestación incluidos (o ambos):

- **Opción A — GitHub Actions (3 repositorios + 3 proyectos GCP)**:
  - Repositorios: `ge-nocode-agents-dev` $\rightarrow$ `ge-nocode-agents-stg` $\rightarrow$ `ge-nocode-agents-prd`
  - Autenticación: **100% Keyless** vía **Workload Identity Federation (OIDC)** con la cuenta de servicio dedicada `ge-cicd-runner@{PROJECT_ID}.iam.gserviceaccount.com`.
- **Opción B — Google Cloud Build (3 repositorios + 3 proyectos GCP)**:
  - Repositorios: `ge-nocode-agents-cb-dev` $\rightarrow$ `ge-nocode-agents-cb-stg` $\rightarrow$ `ge-nocode-agents-cb-prd`
  - Autenticación: **100% Keyless** vía la cuenta de servicio adjunta al trigger de Cloud Build (`ge-cicd-runner@{PROJECT_ID}.iam.gserviceaccount.com`) y **Secret Manager** (`github-token-user`) para la promoción Git entre repositorios.

---

## 2. Prerrequisitos en Google Cloud y GitHub

Antes de iniciar, asegúrate de contar con:

1. **En Google Cloud Platform (GCP)**:
   - **Organization ID** (`ORG_ID`, ej. `298580255441`) y **Billing Account ID** (`BILL_ACT`).
   - **Carpeta Organizacional (`Folder`)**: Puedes usar una carpeta existente (ej. `folders/402619928367`) o dejar `goes_folder_id = ""` en Terraform para que cree automáticamente la carpeta `GOES`.
   - **Proyecto Central para Estado de Terraform (`TF_PROJECT`)**: Un proyecto administrativo (ej. `goes-tf-admin` o `drm-tfproject-000`) donde residirá el bucket GCS centralizado de estado remoto (`BACKEND_BUCKET`, ej. `goes-ge-tf-backend`).
2. **En GitHub**:
   - Una organización o cuenta de GitHub (ej. `gob-sv` o tu usuario corporativo) donde se alojarán los repositorios `dev`, `stg` y `prd`.
   - Un **Personal Access Token (PAT) o Fine-Grained Token** (`TOKEN_USER`) con permisos `repo` y `workflow` para permitir que el job `Send To Next Environment` promueva el código de `dev` $\rightarrow$ `stg` y de `stg` $\rightarrow$ `prd`.
3. **Herramientas Locales (para el bootstrap inicial)**:
   - `gcloud` CLI (`>= 450.0.0`), `terraform` (`>= 1.5.0`), `python3` (`>= 3.11`), `git` y `gh` (GitHub CLI).

---

## 3. Paso 1: Crear el Bucket Central de Estado de Terraform (`BACKEND_BUCKET`)

Ejecuta los siguientes comandos reemplazando las variables con los datos de la organización de GOES:

```bash
export ORG_ID="TU_ORG_ID"
export BILLING_ACCOUNT="TU_BILLING_ACCOUNT_ID"
export GOES_FOLDER_ID="folders/TU_FOLDER_ID"       # O deja vacío "" para crear carpeta nueva
export TF_PROJECT="goes-tf-state-admin"            # Proyecto donde vivirá el bucket de tfstate
export BACKEND_BUCKET="goes-ge-tf-backend"         # Nombre único global del bucket GCS
export GH_OWNER="TU_ORG_O_USUARIO_GITHUB"          # Ej. gob-sv

# Crear el bucket central de estado de Terraform con versionamiento activo
gcloud storage buckets create "gs://${BACKEND_BUCKET}" \
  --project="${TF_PROJECT}" \
  --location="US" \
  --uniform-bucket-level-access
gcloud storage buckets update "gs://${BACKEND_BUCKET}" --versioning
```

---

## 4. Paso 2: Crear y Subir los Repositorios (`dev`, `stg`, `prd`) en GitHub

Descomprime o clona el repositorio base (`ge-nocode-agents-dev`) y crea los repositorios correspondientes en la cuenta de GitHub de GOES:

```bash
# Si vas a implementar Opción A (GitHub Actions):
for env in dev stg prd; do
  REPO_NAME="ge-nocode-agents-${env}"
  gh repo create "${GH_OWNER}/${REPO_NAME}" --private \
    --description "GOES - Gemini Enterprise No-Code Agents CI/CD & ADK Eval (${env^^})"
  git push "https://github.com/${GH_OWNER}/${REPO_NAME}.git" main:main --force
done

# Si también vas a implementar Opción B (Google Cloud Build):
for env in dev stg prd; do
  REPO_NAME="ge-nocode-agents-cb-${env}"
  gh repo create "${GH_OWNER}/${REPO_NAME}" --private \
    --description "GOES - Gemini Enterprise No-Code Agents Cloud Build CI/CD (${env^^})"
  git push "https://github.com/${GH_OWNER}/${REPO_NAME}.git" main:main --force
done
```

> [!TIP]
> Si en `terraform_projects/projects.tf` deseas que el prefijo de los proyectos GCP sea distinto a `goes-ge-gha-{env}` / `goes-ge-cb-{env}`, o que la condición OIDC (`attribute_condition`) apunte a tu organización de GitHub (`assertion.repository_owner == 'TU_ORG_O_USUARIO_GITHUB'`), actualiza [`terraform_projects/projects.tf`](../terraform_projects/projects.tf) antes de hacer push.

---

## 5. Paso 3: Aprovisionar la Landing Zone (`terraform_projects/`) y Keyless WIF

El directorio [`terraform_projects/`](../terraform_projects/) aprovisiona por cada ambiente (`dev`, `stg`, `prd`):
- Los proyectos GCP (`goes-ge-gha-{env}` y/o `goes-ge-cb-{env}`) dentro de la carpeta `GOES`.
- Las APIs necesarias (`discoveryengine.googleapis.com`, `aiplatform.googleapis.com`, `cloudbuild.googleapis.com`, `secretmanager.googleapis.com`, `storage.googleapis.com`, `iam.googleapis.com`, `iamcredentials.googleapis.com`, `sts.googleapis.com`, `cloudresourcemanager.googleapis.com`).
- La cuenta de servicio dedicada **`ge-cicd-runner@{PROJECT_ID}.iam.gserviceaccount.com`** con roles IAM de mínimo privilegio (`roles/discoveryengine.admin`, `roles/aiplatform.user`, `roles/storage.admin`, `roles/secretmanager.secretAccessor`, `roles/cloudbuild.builds.editor`, `roles/serviceusage.serviceUsageAdmin`).
- El **Workload Identity Pool (`github-actions-pool`)** y el **OIDC Provider (`github-provider`)** junto con los bindings `roles/iam.workloadIdentityUser` y `roles/iam.serviceAccountTokenCreator` hacia el repositorio de GitHub correspondiente.

Ejecuta el bootstrap de `terraform_projects/` para cada ambiente (`dev`, `stg`, `prd`):

```bash
cd terraform_projects

for env in dev stg prd; do
  cat > backend.tf <<EOF
terraform {
  backend "gcs" {
    bucket = "${BACKEND_BUCKET}"
    prefix = "${env}/projects/terraform/state"
  }
}
EOF

  cat > spec_variables.auto.tfvars <<EOF
org_id            = "${ORG_ID}"
billing_account   = "${BILLING_ACCOUNT}"
terraform_project = "${TF_PROJECT}"
goes_folder_id    = "${GOES_FOLDER_ID}"
env               = "${env}"
EOF

  terraform init -reconfigure
  terraform apply -auto-approve

  # Otorgar acceso al bucket central de estado de Terraform a las SAs creadas
  for proj in "goes-ge-gha-${env}" "goes-ge-cb-${env}"; do
    gcloud storage buckets add-iam-policy-binding "gs://${BACKEND_BUCKET}" \
      --member="serviceAccount:ge-cicd-runner@${proj}.iam.gserviceaccount.com" \
      --role="roles/storage.admin"
  done
done

cd ..
```

---

## 6. Paso 4: Configurar Variables (`vars.*`) y Secretos en los Repositorios

### 6.1. Matriz de Variables de Repositorio (`GitHub Actions` y `Cloud Build`)

| Variable | Ambiente `DEV` | Ambiente `STG` | Ambiente `PRD` | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `ENV` | `dev` | `stg` | `prd` | Identificador corto del ambiente |
| `GE_PROJECT_ID` | `goes-ge-{gha\|cb}-dev` | `goes-ge-{gha\|cb}-stg` | `goes-ge-{gha\|cb}-prd` | ID del proyecto GCP del ambiente |
| `GE_LOCATION` | `global` | `global` | `global` | Ubicación de Discovery Engine (`global`, `us`, `eu`) |
| `GE_ENGINE_ID` | `sv-citizen-engine` | `sv-citizen-engine` | `sv-citizen-engine` | ID de la aplicación/motor en Gemini Enterprise |
| `GE_DATA_STORE_ID` | `sv-tramites-datastore` | `sv-tramites-datastore` | `sv-tramites-datastore` | ID del Data Store de Vertex AI Search |
| `GE_SHARING_SCOPE` | `PRIVATE` | `RESTRICTED` | `ALL_USERS` | Alcance de publicación del agente por ambiente |
| `WIF_PROVIDER` | `projects/{NUM_DEV}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider` | `projects/{NUM_STG}/...` | `projects/{NUM_PRD}/...` | Proveedor OIDC para autenticación Keyless |
| `WIF_SERVICE_ACCOUNT` | `ge-cicd-runner@goes-ge-{gha\|cb}-dev.iam.gserviceaccount.com` | `ge-cicd-runner@...-stg...` | `ge-cicd-runner@...-prd...` | Cuenta de servicio que personifica el runner |
| `TF_PROJECT` | `${TF_PROJECT}` | `${TF_PROJECT}` | `${TF_PROJECT}` | Proyecto que aloja el bucket central de Terraform |
| `BACKEND_BUCKET` | `${BACKEND_BUCKET}` | `${BACKEND_BUCKET}` | `${BACKEND_BUCKET}` | Nombre del bucket GCS para estado remoto de Terraform |
| `TARGET_ENV` | `stg` | `prd` | *(Omitir en PRD)* | Siguiente ambiente en la cadena de promoción |
| `SOURCE_REPO_FN` | `${GH_OWNER}/ge-nocode-agents{-cb}-dev.git` | `${GH_OWNER}/ge-nocode-agents{-cb}-stg.git` | *(Omitir en PRD)* | Repositorio origen para `Send To Next Environment` |
| `SOURCE_REPO_SN` | `ge-nocode-agents{-cb}-dev` | `ge-nocode-agents{-cb}-stg` | *(Omitir en PRD)* | Nombre corto del directorio clonado al promover |
| `TARGET_REPO_FN` | `${GH_OWNER}/ge-nocode-agents{-cb}-stg.git` | `${GH_OWNER}/ge-nocode-agents{-cb}-prd.git` | *(Omitir en PRD)* | Repositorio destino al que se hace `git push` |

### 6.2. Script Automatizado para Configurar Variables y Secretos con `gh`

Puedes ejecutar este bloque para configurar automáticamente los 3 repositorios de GitHub Actions (`ge-nocode-agents-{dev,stg,prd}`):

```bash
export GITHUB_PAT_PROMOTE="ghp_TU_TOKEN_CON_PERMISOS_REPO_Y_WORKFLOW"

for env in dev stg prd; do
  REPO="${GH_OWNER}/ge-nocode-agents-${env}"
  PROJ="goes-ge-gha-${env}"
  PROJ_NUM=$(gcloud projects describe "${PROJ}" --format="value(projectNumber)")
  WIF_PROV="projects/${PROJ_NUM}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider"
  WIF_SA="ge-cicd-runner@${PROJ}.iam.gserviceaccount.com"

  gh variable set ENV --body "${env}" -R "${REPO}"
  gh variable set GE_PROJECT_ID --body "${PROJ}" -R "${REPO}"
  gh variable set GE_LOCATION --body "global" -R "${REPO}"
  gh variable set GE_ENGINE_ID --body "sv-citizen-engine" -R "${REPO}"
  gh variable set GE_DATA_STORE_ID --body "sv-tramites-datastore" -R "${REPO}"
  gh variable set TF_PROJECT --body "${TF_PROJECT}" -R "${REPO}"
  gh variable set BACKEND_BUCKET --body "${BACKEND_BUCKET}" -R "${REPO}"
  gh variable set WIF_PROVIDER --body "${WIF_PROV}" -R "${REPO}"
  gh variable set WIF_SERVICE_ACCOUNT --body "${WIF_SA}" -R "${REPO}"

  # Secreto TOKEN_USER para promover código al siguiente ambiente
  gh secret set TOKEN_USER --body "${GITHUB_PAT_PROMOTE}" -R "${REPO}"
done

# Variables específicas por etapa del ciclo de vida
gh variable set GE_SHARING_SCOPE --body "PRIVATE" -R "${GH_OWNER}/ge-nocode-agents-dev"
gh variable set TARGET_ENV --body "stg" -R "${GH_OWNER}/ge-nocode-agents-dev"
gh variable set SOURCE_REPO_FN --body "${GH_OWNER}/ge-nocode-agents-dev.git" -R "${GH_OWNER}/ge-nocode-agents-dev"
gh variable set SOURCE_REPO_SN --body "ge-nocode-agents-dev" -R "${GH_OWNER}/ge-nocode-agents-dev"
gh variable set TARGET_REPO_FN --body "${GH_OWNER}/ge-nocode-agents-stg.git" -R "${GH_OWNER}/ge-nocode-agents-dev"

gh variable set GE_SHARING_SCOPE --body "RESTRICTED" -R "${GH_OWNER}/ge-nocode-agents-stg"
gh variable set TARGET_ENV --body "prd" -R "${GH_OWNER}/ge-nocode-agents-stg"
gh variable set SOURCE_REPO_FN --body "${GH_OWNER}/ge-nocode-agents-stg.git" -R "${GH_OWNER}/ge-nocode-agents-stg"
gh variable set SOURCE_REPO_SN --body "ge-nocode-agents-stg" -R "${GH_OWNER}/ge-nocode-agents-stg"
gh variable set TARGET_REPO_FN --body "${GH_OWNER}/ge-nocode-agents-prd.git" -R "${GH_OWNER}/ge-nocode-agents-stg"

gh variable set GE_SHARING_SCOPE --body "ALL_USERS" -R "${GH_OWNER}/ge-nocode-agents-prd"
```

> [!NOTE]
> **Si utilizas Opción B (Google Cloud Build)**:
> Guarda el token de GitHub en Secret Manager en cada proyecto (`goes-ge-cb-{dev,stg,prd}`) bajo el nombre `github-token-user`:
> ```bash
> for env in dev stg prd; do
>   printf "%s" "${GITHUB_PAT_PROMOTE}" | gcloud secrets create github-token-user \
>     --project="goes-ge-cb-${env}" --replication-policy="automatic" --data-file=- || \
>   printf "%s" "${GITHUB_PAT_PROMOTE}" | gcloud secrets versions add github-token-user \
>     --project="goes-ge-cb-${env}" --data-file=-
> done
> ```

---

## 7. Paso 5: Desplegar los Servicios Base de Gemini Enterprise (`terraform_services/`)

En cada uno de los 3 repositorios (`dev`, `stg`, `prd`), ejecuta el workflow **`Terraform Services Actions`** ([`.github/workflows/terraform_services.yml`](../.github/workflows/terraform_services.yml)):

```bash
for env in dev stg prd; do
  gh workflow run terraform_services.yml -R "${GH_OWNER}/ge-nocode-agents-${env}"
done
```

¿Qué hace automáticamente este workflow en cada proyecto (`dev`, `stg`, `prd`)?
1. Crea el bucket GCS del corpus (`{GE_PROJECT_ID}-ge-corpus-{env}`) y sube el documento normativo [`agents/sv_citizen_assistant/corpus/manual_oficial_tramites_sv.md`](../agents/sv_citizen_assistant/corpus/manual_oficial_tramites_sv.md).
2. Aprovisiona el Data Store nativo en Terraform (`google_discovery_engine_data_store.tramites_ds` $\rightarrow$ `sv-tramites-datastore`).
3. Ejecuta el recurso declarativo `terraform_data.gemini_enterprise_engine_and_corpus` que invoca [`cli/ensure_ge_infra.py`](../cli/ensure_ge_infra.py) para reconciliar idempotentemente en la API `v1alpha`:
   - `LicenseConfig` y `UserStore` (`enableLicenseAutoRegister: true`).
   - El documento indexado `manual-oficial-tramites-goes-2026` dentro de `sv-tramites-datastore`.
   - El motor de Gemini Enterprise (`sv-citizen-engine` con `APP_TYPE_INTRANET` y `SEARCH_ADD_ON_LLM`).
   - El asistente por defecto (`default_assistant`).

---

## 8. Paso 6: Crear/Editar el Agente No-Code en `DEV` y Ejecutar el Ciclo `DEV` $\rightarrow$ `STG` $\rightarrow$ `PRD`

### 8.1. Sembrar o Diseñar el Agente Inicial en `DEV`
Si estás partiendo de un proyecto `DEV` recién creado y quieres cargar la plantilla base [`agents/sv_citizen_assistant/agent_template.json`](../agents/sv_citizen_assistant/agent_template.json) hacia la consola visual de Agent Designer en `DEV`, ejecuta una única vez `push`:

```bash
ENV=dev \
GE_PROJECT_ID="goes-ge-gha-dev" \
GE_LOCATION="global" \
GE_ENGINE_ID="sv-citizen-engine" \
GE_DATA_STORE_ID="sv-tramites-datastore" \
GE_SHARING_SCOPE="PRIVATE" \
python3 cli/ge_agent_cli.py push \
  --template-path agents/sv_citizen_assistant/agent_template.json
```

A partir de ese momento:
1. **Diseño Visual en `DEV`**: Los analistas o diseñadores de GOES entran a **Google Cloud Console $\rightarrow$ Gemini Enterprise $\rightarrow$ Apps $\rightarrow$ `sv-citizen-engine` $\rightarrow$ Agent Designer** en el proyecto `DEV` y ajustan instrucciones, *starter prompts* o herramientas sin escribir código.
2. **Extracción y Evaluación en `DEV`**:
   - Para traer los cambios hechos en la UI de `DEV` hacia Git, ejecuta:
     ```bash
     python3 cli/ge_agent_cli.py pull \
       --project-id goes-ge-gha-dev \
       --location global \
       --engine-id sv-citizen-engine \
       --data-store-id sv-tramites-datastore \
       --template-path agents/sv_citizen_assistant/agent_template.json
     ```
   - Al hacer `git commit` y `git push origin main` en `ge-nocode-agents-dev` (o al disparar `GE No-Code Agent Deploy & ADK Eval Actions`), el workflow en `DEV` verifica la extracción (`pull`) y ejecuta la compuerta de calidad **`eval/run_eval.py`** (**8 casos del Golden Dataset $\times$ 4 métricas de `google-adk` = 32 evaluaciones**).
3. **Promoción `DEV` $\rightarrow$ `STG`**:
   - En `ge-nocode-agents-dev`, ejecuta el workflow **`Send To Next Environment`** (o `cloudbuild_deployment_actions.yaml` en Cloud Build).
   - Esto empuja el código validado hacia `ge-nocode-agents-stg`, donde automáticamente:
     - Se hidrata `agent_template.json` con `ENV=stg` y `GE_PROJECT_ID=goes-ge-gha-stg`.
     - Se ejecuta `cli/ge_agent_cli.py push` (`CreateAgent`/`UpdateAgent` + `:deployLowCode`).
     - Se ejecutan las 32 evaluaciones de `google-adk` contra el agente de `STG`.
     - Si aprueba al 100%, se ejecuta `cli/ge_agent_cli.py request-review` (`:requestAgentReview` + alcance `RESTRICTED`) para pruebas de aceptación humana (HITL / UAT).
4. **Promoción `STG` $\rightarrow$ `PRD` y Publicación Inmutable**:
   - Una vez aprobado por los revisores en `STG`, ejecuta **`Send To Next Environment`** en `ge-nocode-agents-stg`.
   - Esto promueve el código a `ge-nocode-agents-prd`, donde automáticamente:
     - Se hidrata `agent_template.json` con `ENV=prd` y `GE_PROJECT_ID=goes-ge-gha-prd`.
     - Se despliega y compila el agente con `:deployLowCode`.
     - Se ejecuta el Smoke Test completo de `google-adk` (32 evaluaciones).
     - Si aprueba al 100%, se ejecuta `cli/ge_agent_cli.py publish`, que habilita el agente (`ENABLED`), configura `sharingConfig.scope = ALL_USERS` e invoca **`:publish`** generando una **`AgentRevision` inmutable** vinculada en `activeRevision`.

---

## 9. Cómo Adaptar esta Plantilla para Nuevos Agentes o Instituciones del GOES

Para reutilizar esta arquitectura con cualquier otro ministerio o institución (ej. Ministerio de Hacienda, MINSAL, MINED, Defensoría del Consumidor):

1. **Actualizar el Corpus Documental (RAG)**:
   - Reemplaza o agrega los documentos normativos en `agents/<nombre_agente>/corpus/` y actualiza la ruta `corpus_filepath` en [`terraform_services/main.tf`](../terraform_services/main.tf). Al correr `terraform apply`, el hash `filemd5` detectará el cambio y re-indexará el documento automáticamente.
2. **Diseñar el Nuevo Agente en Agent Designer (`DEV`) y Exportarlo**:
   - Crea el agente en la UI de Agent Designer en `DEV`, conéctalo al Data Store y ejecuta `python3 cli/ge_agent_cli.py pull --template-path agents/<nombre_agente>/agent_template.json`.
3. **Definir el Golden Dataset (`golden_dataset.evalset.json`) y las Rúbricas (`eval_config.json`)**:
   - Agrega los casos de prueba representativos de la institución (un turno, multi-turno y casos de rechazo/guardrail fuera de alcance) en `golden_dataset.evalset.json`.
   - Ajusta los umbrales (`threshold`) y las rúbricas específicas del dominio en `eval_config.json`.
