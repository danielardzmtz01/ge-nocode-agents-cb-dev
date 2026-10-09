# Documentación Técnica y Operativa: CI/CD In-Place (`dev` $\rightarrow$ `stg` $\rightarrow$ `prd`) y Evaluación Automatizada (`google-adk`) para Agentes No-Code en Gemini Enterprise (GOES)

> [!IMPORTANT]
> **Resumen Ejecutivo**: Esta documentación describe la arquitectura, el modelo de gobierno y la implementación en vivo de **Integración, Evaluación Continua (`google-adk`) y Promoción In-Place Multi-Repositorio (`dev` $\rightarrow$ `stg` $\rightarrow$ `prd`)** para agentes **No-Code / Low-Code** creados en **Gemini Enterprise (Agent Designer)** para el **Gobierno de El Salvador (GOES)**. Incluye dos implementaciones completas desplegadas y certificadas en vivo dentro de la carpeta de Google Cloud **`GOES` (`folders/402619928367`)**:
> 1. **Opción A — GitHub Actions**: 3 repositorios (`ge-nocode-agents-{dev,stg,prd}`) desplegados contra 3 proyectos GCP (`goes-ge-gha-{dev,stg,prd}`).
> 2. **Opción B — Google Cloud Build**: 3 repositorios (`ge-nocode-agents-cb-{dev,stg,prd}`) desplegados y promovidos con Cloud Build contra 3 proyectos GCP (`goes-ge-cb-{dev,stg,prd}`).

---

## 1. Diagramas de Arquitectura Corporativa (`GitHub Actions` y `Google Cloud Build`)

Ambos flujos siguen el patrón **In-Place Multi-Repositorio (`Send To Next Environment`)**, donde los 3 repositorios (`dev`, `stg`, `prd`) mantienen **exactamente el mismo código fuente** sin IDs quemados (*hardcoded*). En tiempo de ejecución, el pipeline genera *in-place* el archivo `spec_variables.auto.yaml`, hidrata la plantilla del agente ([`agent_template.json`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/agents/sv_citizen_assistant/agent_template.json)), compila el grafo No-Code en Gemini Enterprise (`:deployLowCode`), ejecuta la compuerta de calidad con **`google-adk`** ([`run_eval.py`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/eval/run_eval.py)) y promueve el código al siguiente ambiente.

````carousel
### Opción A: Arquitectura CI/CD In-Place con GitHub Actions (`goes-ge-gha-{dev,stg,prd}`)

```mermaid
---
config:
  layout: elk
  look: neo
  theme: default
themeVariables:
  fontFamily: 'Roboto, Google Sans, Helvetica, Arial, sans-serif'
  primaryColor: '#4285F4'
  secondaryColor: '#34A853'
  tertiaryColor: '#FBBC04'
  mainBkg: '#FFFFFF'
  nodeBorder: '#4285F4'
  clusterBkg: '#F8F9FA'
  clusterBorder: '#DADCE0'
  lineColor: '#5F6368'
  edgeLabelBackground: '#ffffff'
---
flowchart TD
    subgraph ROW1[" "]
        direction LR
        subgraph SG_Design["1. Diseño & Exportación (UI a GitOps)"]
            direction LR
            Designer["`**Diseñador de Agentes**<br>Gobierno de El Salvador`"]:::gcpBlue
            Designer@{ icon: "fa:user" }
            GE_UI["`**GE Agent Designer UI**<br>No-Code / Low-Code`"]:::gcpBlue
            GE_UI@{ icon: "gcp:vertexai" }
            Pull_CLI["`**ge_agent_cli.py pull**<br>GetAgent + Parametrización`"]
            Pull_CLI@{ icon: "logos:python" }

            Designer --> GE_UI --> Pull_CLI
        end
    end

    Pull_CLI --> wpA_src((("A"))):::wp_blue

    subgraph SG_Dev["2. Ambiente DEV (Folder GOES: goes-ge-gha-dev | ge-nocode-agents-dev)"]
        direction LR
        wpA_dst((("A"))):::wp_blue
        Repo_Dev["`**Repo GitHub DEV**<br>agent_template.json + EvalSet`"]
        Repo_Dev@{ icon: "logos:github" }
        CI_Dev["`**GitHub Actions**<br>Hidrata spec_variables.auto.yaml`"]:::gcpBlue
        CI_Dev@{ icon: "gcp:cloud-build" }
        GE_Dev["`**Gemini Enterprise DEV**<br>:deployLowCode (Scope: PRIVATE)`"]:::gcpBlue
        GE_Dev@{ icon: "gcp:vertexai" }
        ADK_Dev["`**Adapter :streamAssist -> ADK**<br>8 Casos Golden Dataset Gate`"]:::gcpGreen
        ADK_Dev@{ icon: "gcp:vertexai" }

        wpA_dst ==> Repo_Dev --> CI_Dev --> GE_Dev --> ADK_Dev
    end

    ADK_Dev -->|"Score >= Threshold (32/32 PASSED)<br>Send To Next Environment"| wpB_src((("B"))):::wp_green

    subgraph SG_Stg["3. Ambiente STG + Revisión HITL (Folder GOES: goes-ge-gha-stg | ge-nocode-agents-stg)"]
        direction LR
        wpB_dst((("B"))):::wp_green
        Repo_Stg["`**Repo GitHub STG**<br>Promoción In-Place (main)`"]
        Repo_Stg@{ icon: "logos:github" }
        CI_Stg["`**GitHub Actions**<br>Hidrata ENV=stg`"]:::gcpYellow
        CI_Stg@{ icon: "gcp:cloud-build" }
        GE_Stg["`**Gemini Enterprise STG**<br>:deployLowCode + :requestAgentReview`"]:::gcpYellow
        GE_Stg@{ icon: "gcp:vertexai" }
        HITL["`**Validación HITL + ADK Gate**<br>Scope: RESTRICTED (ENABLED)`"]:::gcpYellow
        HITL@{ icon: "fa:user" }

        wpB_dst ==> Repo_Stg --> CI_Stg --> GE_Stg --> HITL
    end

    HITL -->|"Aprobación HITL<br>Send To Next Environment"| wpC_src((("C"))):::wp_yellow

    subgraph SG_Prd["4. Ambiente PRD & Gobernanza (Folder GOES: goes-ge-gha-prd | ge-nocode-agents-prd)"]
        direction LR
        wpC_dst((("C"))):::wp_yellow
        Repo_Prd["`**Repo GitHub PRD**<br>Guard: !contains(prd)`"]
        Repo_Prd@{ icon: "logos:github" }
        CI_Prd["`**GitHub Actions**<br>Hidrata ENV=prd`"]:::gcpGreen
        CI_Prd@{ icon: "gcp:cloud-build" }
        GE_Prd["`**Gemini Enterprise PRD**<br>:deployLowCode + Smoke Test ADK`"]:::gcpGreen
        GE_Prd@{ icon: "gcp:vertexai" }
        Pub_Prd["`**Release Inmutable Ciudadano**<br>:publish + activeRevision`"]:::gcpRed
        Pub_Prd@{ icon: "gcp:vertexai" }

        wpC_dst ==> Repo_Prd --> CI_Prd --> GE_Prd --> Pub_Prd
    end

    ROW1 ~~~ SG_Dev ~~~ SG_Stg ~~~ SG_Prd

    classDef gcpBlue fill:#E8F0FE,stroke:#1967D2,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpGreen fill:#E6F4EA,stroke:#1E8E3E,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpYellow fill:#FEF7E0,stroke:#B06000,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpRed fill:#FCE8E6,stroke:#D93025,stroke-width:2px,color:#000,font-family:Roboto;
    classDef wp_blue fill:#1A73E8,stroke:#0D47A1,stroke-width:2px,color:#fff,font-weight:bold;
    classDef wp_green fill:#34A853,stroke:#1B5E20,stroke-width:2px,color:#fff,font-weight:bold;
    classDef wp_yellow fill:#FBBC04,stroke:#F29900,stroke-width:2px,color:#000,font-weight:bold;

    style ROW1 fill:none,stroke:none
    style SG_Design fill:#ffffff,stroke:#9E9E9E,stroke-dasharray:5 5,stroke-width:2px
    style SG_Dev fill:#e8f0fe,stroke:#1967D2,stroke-width:2px
    style SG_Stg fill:#f9f9f9,stroke:#DADCE0,stroke-width:2px
    style SG_Prd fill:#e6f4ea,stroke:#1E8E3E,stroke-width:2px
```
<!-- slide -->
### Opción B: Arquitectura CI/CD In-Place con Google Cloud Build (`goes-ge-cb-{dev,stg,prd}`)

```mermaid
---
config:
  layout: elk
  look: neo
  theme: default
themeVariables:
  fontFamily: 'Roboto, Google Sans, Helvetica, Arial, sans-serif'
  primaryColor: '#4285F4'
  secondaryColor: '#34A853'
  tertiaryColor: '#FBBC04'
  mainBkg: '#FFFFFF'
  nodeBorder: '#4285F4'
  clusterBkg: '#F8F9FA'
  clusterBorder: '#DADCE0'
  lineColor: '#5F6368'
  edgeLabelBackground: '#ffffff'
---
flowchart TD
    subgraph ROW1[" "]
        direction LR
        subgraph SG_Design["1. Diseño & Exportación (UI a GitOps)"]
            direction LR
            Designer["`**Diseñador de Agentes**<br>Gobierno de El Salvador`"]:::gcpBlue
            Designer@{ icon: "fa:user" }
            GE_UI["`**GE Agent Designer UI**<br>No-Code / Low-Code`"]:::gcpBlue
            GE_UI@{ icon: "gcp:vertexai" }
            Pull_CLI["`**ge_agent_cli.py pull**<br>GetAgent + Parametrización`"]
            Pull_CLI@{ icon: "logos:python" }

            Designer --> GE_UI --> Pull_CLI
        end
    end

    Pull_CLI --> wpA_src((("A"))):::wp_blue

    subgraph SG_Dev["2. Proyecto GCP DEV (Folder GOES: goes-ge-cb-dev | ge-nocode-agents-cb-dev)"]
        direction LR
        wpA_dst((("A"))):::wp_blue
        Repo_Dev["`**Repo GitHub DEV**<br>ge-nocode-agents-cb-dev`"]
        Repo_Dev@{ icon: "logos:github" }
        CB_Deploy_Dev["`**Cloud Build Deploy & Eval**<br>cloudbuild_deploy_and_eval.yaml (_ENV=dev)`"]:::gcpBlue
        CB_Deploy_Dev@{ icon: "gcp:cloud-build" }
        GE_Dev["`**Gemini Enterprise DEV**<br>:deployLowCode + :streamAssist ADK Gate`"]:::gcpGreen
        GE_Dev@{ icon: "gcp:vertexai" }
        SM_Dev["`**Secret Manager**<br>github-token-user + ge-adc-credentials`"]:::gcpBlue
        SM_Dev@{ icon: "gcp:secret-manager" }
        CB_Promo_Dev["`**Cloud Build Promote**<br>cloudbuild_deployment_actions.yaml`"]:::gcpBlue
        CB_Promo_Dev@{ icon: "gcp:cloud-build" }

        wpA_dst ==> Repo_Dev --> CB_Deploy_Dev --> GE_Dev --> CB_Promo_Dev
        SM_Dev -.->|"Inyecta secretEnv"| CB_Promo_Dev
    end

    CB_Promo_Dev -->|"git push target-repo main --force<br>(Promoción DEV -> STG)"| wpB_src((("B"))):::wp_green

    subgraph SG_Stg["3. Proyecto GCP STG + Aprobación HITL (Folder GOES: goes-ge-cb-stg | ge-nocode-agents-cb-stg)"]
        direction LR
        wpB_dst((("B"))):::wp_green
        Repo_Stg["`**Repo GitHub STG**<br>ge-nocode-agents-cb-stg`"]
        Repo_Stg@{ icon: "logos:github" }
        CB_Deploy_Stg["`**Cloud Build Deploy & Eval**<br>cloudbuild_deploy_and_eval.yaml (_ENV=stg)`"]:::gcpYellow
        CB_Deploy_Stg@{ icon: "gcp:cloud-build" }
        GE_Stg["`**Gemini Enterprise STG**<br>:deployLowCode + ADK + :requestAgentReview`"]:::gcpYellow
        GE_Stg@{ icon: "gcp:vertexai" }
        HITL_Stg["`**Aprobación HITL**<br>Cloud Build Approval Gate + Scope RESTRICTED`"]:::gcpYellow
        HITL_Stg@{ icon: "fa:user" }
        CB_Promo_Stg["`**Cloud Build Promote**<br>cloudbuild_deployment_actions.yaml`"]:::gcpYellow
        CB_Promo_Stg@{ icon: "gcp:cloud-build" }

        wpB_dst ==> Repo_Stg --> CB_Deploy_Stg --> GE_Stg --> HITL_Stg --> CB_Promo_Stg
    end

    CB_Promo_Stg -->|"git push target-repo main --force<br>(Promoción STG -> PRD)"| wpC_src((("C"))):::wp_yellow

    subgraph SG_Prd["4. Proyecto GCP PRD & Gobernanza (Folder GOES: goes-ge-cb-prd | ge-nocode-agents-cb-prd)"]
        direction LR
        wpC_dst((("C"))):::wp_yellow
        Repo_Prd["`**Repo GitHub PRD**<br>ge-nocode-agents-cb-prd`"]
        Repo_Prd@{ icon: "logos:github" }
        CB_Deploy_Prd["`**Cloud Build Deploy & Eval**<br>cloudbuild_deploy_and_eval.yaml (_ENV=prd)`"]:::gcpGreen
        CB_Deploy_Prd@{ icon: "gcp:cloud-build" }
        GE_Prd["`**Gemini Enterprise PRD**<br>:deployLowCode + Smoke Test ADK`"]:::gcpGreen
        GE_Prd@{ icon: "gcp:vertexai" }
        Pub_Prd["`**Release Inmutable Ciudadano**<br>:publish + activeRevision`"]:::gcpRed
        Pub_Prd@{ icon: "gcp:vertexai" }
        Logs_Prd["`**Cloud Logging**<br>CLOUD_LOGGING_ONLY + Auditoría ADK`"]:::gcpBlue
        Logs_Prd@{ icon: "gcp:cloud-logging" }

        wpC_dst ==> Repo_Prd --> CB_Deploy_Prd --> GE_Prd --> Pub_Prd
        CB_Deploy_Prd -.->|"Trazabilidad"| Logs_Prd
    end

    ROW1 ~~~ SG_Dev ~~~ SG_Stg ~~~ SG_Prd

    classDef gcpBlue fill:#E8F0FE,stroke:#1967D2,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpGreen fill:#E6F4EA,stroke:#1E8E3E,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpYellow fill:#FEF7E0,stroke:#B06000,stroke-width:2px,color:#000,font-family:Roboto;
    classDef gcpRed fill:#FCE8E6,stroke:#D93025,stroke-width:2px,color:#000,font-family:Roboto;
    classDef wp_blue fill:#1A73E8,stroke:#0D47A1,stroke-width:2px,color:#fff,font-weight:bold;
    classDef wp_green fill:#34A853,stroke:#1B5E20,stroke-width:2px,color:#fff,font-weight:bold;
    classDef wp_yellow fill:#FBBC04,stroke:#F29900,stroke-width:2px,color:#000,font-weight:bold;

    style ROW1 fill:none,stroke:none
    style SG_Design fill:#ffffff,stroke:#9E9E9E,stroke-dasharray:5 5,stroke-width:2px
    style SG_Dev fill:#e8f0fe,stroke:#1967D2,stroke-width:2px
    style SG_Stg fill:#f9f9f9,stroke:#DADCE0,stroke-width:2px
    style SG_Prd fill:#e6f4ea,stroke:#1E8E3E,stroke-width:2px
```
````

---

## 2. Inventario de Recursos Desplegados en Vivo (`folders/402619928367` — `GOES`)

Todos los recursos fueron aprovisionados dentro de la carpeta **`GOES` (`folders/402619928367`)** en la organización `danielardzmtz.altostrat.com` (`298580255441`). Cada uno de los 6 proyectos cuenta con:
- **Licenciamiento Gemini Enterprise**: `LicenseConfig` (`free_trial_gemini`), `UserStore` (`default_user_store` con `enableLicenseAutoRegister: true`) y `UserLicense` asignada a `admin@danielardzmtz.altostrat.com`.
- **Vertex AI Search Data Store (RAG)**: `sv-tramites-datastore` con el documento normativo indexado `manual-oficial-tramites-goes-2026` (*RNPN, DGME, Centros Penales, SERTRACEN y VMT*).
- **Gemini Enterprise Engine & Assistant**: `sv-citizen-engine` (`SOLUTION_TYPE_GENERATIVE_CHAT`, `APP_TYPE_INTRANET`) + `assistants/default_assistant`.

### 2.1. Ejemplo 1: Flujo Multi-Repo con **GitHub Actions** (`goes-ge-gha-{dev,stg,prd}`)

| Ambiente | Repositorio GitHub | Proyecto GCP (`folders/402619928367`) | Project Number | Agent ID en GE | Estado / Sharing Scope | Active Revision (`:publish`) | Ejecución Certificada |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`DEV`** | `danielardzmtz01/ge-nocode-agents-dev` | `goes-ge-gha-dev` | `1076809815833` | `2172421677339450929` | `PRIVATE` / `ENABLED` | `5074119707885744899` | `ge_agent_deploy_and_eval.yml` (`32/32 PASSED`) $\rightarrow$ `deployment_actions.yml` (`DEV -> STG`) |
| **`STG`** | `danielardzmtz01/ge-nocode-agents-stg` | `goes-ge-gha-stg` | `345628853626` | `11971858956007198093` | `ENABLED` / `RESTRICTED` (`:requestAgentReview`) | — | Run `#37829481031` (`32/32 PASSED`) $\rightarrow$ Run `#37829865204` (`STG -> PRD`) |
| **`PRD`** | `danielardzmtz01/ge-nocode-agents-prd` | `goes-ge-gha-prd` | `30228259118` | `3395946724750775553` | `ENABLED` / `ALL_USERS` (`:publish`) | **`14012846407794653890`** | Run `#37830002863` (`32/32 PASSED` + Revisión Inmutable) |

### 2.2. Ejemplo 2: Flujo Multi-Repo con **Google Cloud Build** (`goes-ge-cb-{dev,stg,prd}`)

| Ambiente | Repositorio GitHub | Proyecto GCP (`folders/402619928367`) | Project Number | Agent ID en GE | Estado / Sharing Scope | Active Revision (`:publish`) | Build IDs de Cloud Build |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`DEV`** | `danielardzmtz01/ge-nocode-agents-cb-dev` | `goes-ge-cb-dev` | `601937217732` | `14529129893765249992` | `PRIVATE` / `PRIVATE` (`:deployLowCode`) | — | Deploy & Eval: `2cc7b284-2305-40c1-94b7-5d8baf86dcdd`<br>Promote `DEV -> STG`: `d54271cb-20d3-46cd-9c35-095b20b7c65c` |
| **`STG`** | `danielardzmtz01/ge-nocode-agents-cb-stg` | `goes-ge-cb-stg` | `425990910052` | `4987620311259970191` | `ENABLED` / `RESTRICTED` (`:requestAgentReview`) | — | Deploy & Eval: `49333be0-9f9f-4aeb-93a0-a83de0d0667f`<br>Promote `STG -> PRD`: `0799e90e-16ff-4630-965d-6616d87a3e7f` |
| **`PRD`** | `danielardzmtz01/ge-nocode-agents-cb-prd` | `goes-ge-cb-prd` | `1068386666374` | `3632113936026526418` | `ENABLED` / `ALL_USERS` (`:publish`) | **`8793931032536939173`** | Deploy, Eval & Publish: `9d873c5e-e35d-4025-8483-4aa13fea0f91` |

---

## 3. Estructura del Código y Componentes Clave

```text
.
├── .github/workflows/                         # OPCIÓN A: Pipelines de GitHub Actions
│   ├── ge_agent_deploy_and_eval.yml           # Hidrata spec_variables.auto.yaml, despliega con :deployLowCode, evalúa con ADK y publica
│   └── deployment_actions.yml                 # "Send To Next Environment" (clona SOURCE_REPO_FN y hace push a TARGET_REPO_FN)
├── cloudbuild/                                # OPCIÓN B: Pipelines de Google Cloud Build
│   ├── cloudbuild_deploy_and_eval.yaml        # Pipeline equivalente en Cloud Build con Secret Manager y CLOUD_LOGGING_ONLY
│   └── cloudbuild_deployment_actions.yaml     # Promoción In-Place (DEV -> STG -> PRD) desde Cloud Build
├── cli/
│   └── ge_agent_cli.py                        # CLI GitOps: pull, push (:deployLowCode), request-review, publish (/revisions) y rollback
├── eval/
│   ├── ge_adk_adapter.py                      # Invoca :streamAssist en GE y traduce la respuesta a google.adk.evaluation.eval_case.Invocation
│   └── run_eval.py                            # Ejecuta el Golden Dataset concurrentemente con los evaluadores oficiales de google-adk
├── agents/
│   └── sv_citizen_assistant/
│       ├── agent_template.json                # Definición declarativa del Agente No-Code con placeholders (${ENV}, ${GE_PROJECT_ID}, ...)
│       ├── eval_config.json                   # Umbrales y rúbricas oficiales de google-adk
│       ├── golden_dataset.evalset.json        # 8 casos del Golden Dataset del Gobierno de El Salvador (formato ADK EvalSet)
│       └── corpus/
│           └── manual_oficial_tramites_sv.md  # Corpus normativo oficial indexado en sv-tramites-datastore
└── docs/
    ├── GUIA_ARQUITECTURA_Y_OPERACION.md       # Manual técnico detallado en el repositorio
    └── diagrams/                              # Diagramas Mermaid (.mmd) de GitHub Actions y Cloud Build
```

---

## 4. Funcionamiento Interno del Ciclo de Vida del Agente No-Code en Discovery Engine `v1alpha`

### 4.1. Creación Visual y Extracción Parametrizada (`pull`)
1. Un diseñador funcional crea o ajusta el agente en la consola visual **Gemini Enterprise Agent Designer** en el proyecto `DEV`.
2. Ejecuta [`cli/ge_agent_cli.py`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/cli/ge_agent_cli.py) con el subcomando `pull`:
   ```bash
   python3 cli/ge_agent_cli.py pull \
     --project-id goes-ge-gha-dev \
     --location global \
     --engine-id sv-citizen-engine \
     --agent-id 2172421677339450929 \
     --data-store-id sv-tramites-datastore \
     --template-path agents/sv_citizen_assistant/agent_template.json
   ```
3. El comando `pull` elimina metadatos de solo lectura (`name`, `state`, `createTime`, `updateTime`) y reemplaza automáticamente el ID/número de proyecto, ubicación, Data Store y alcance por placeholders (`${ENV}`, `${GE_PROJECT_ID}`, `${GE_LOCATION}`, `${GE_DATA_STORE_ID}`, `${GE_SHARING_SCOPE}`).

### 4.2. Hidratación In-Place y Compilación ADK Gestionada (`push` + `:deployLowCode`)
1. En tiempo de ejecución, el pipeline crea `spec_variables.auto.yaml` con los valores del ambiente activo (`dev`, `stg` o `prd`).
2. `ge_agent_cli.py push` hidrata [`agent_template.json`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/agents/sv_citizen_assistant/agent_template.json) y resuelve dinámicamente el **`project_number` numérico** vía Cloud Resource Manager API para los `dataStoreSpecs` dentro de `lowCodeAgentDefinition.nodes[*].llmAgentNode.dataStoreSpecs` (requisito estricto del compilador interno de Discovery Engine).
3. Invoca `CreateAgent` (`POST .../agents`) o `UpdateAgent` (`PATCH .../agents/{id}?updateMask=displayName,description,lowCodeAgentDefinition`).
4. Invoca el endpoint de compilación:
   ```http
   POST https://discoveryengine.googleapis.com/v1alpha/{agent_name}:deployLowCode
   {
     "name": "projects/{project_number}/locations/global/collections/default_collection/engines/sv-citizen-engine/assistants/default_assistant/agents/{agent_id}",
     "deployMode": "DEPLOY"
   }
   ```

### 4.3. Adaptador `:streamAssist` $\rightarrow$ `google-adk` y Compuerta de Calidad (`eval/run_eval.py`)
Dado que los agentes No-Code viven dentro del runtime gestionado de Gemini Enterprise y se consumen por `POST /v1alpha/{assistant}:streamAssist`, el adaptador [`eval/ge_adk_adapter.py`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/eval/ge_adk_adapter.py) construye objetos nativos `google.adk.evaluation.eval_case.Invocation` compatibles con todos los evaluadores oficiales de `google-adk`:
- **`app_details` (`AppDetails`)**: Registra las instrucciones del sistema (`root_citizen_router`) y la declaración formal de la herramienta `vertex_ai_search` para que los jueces LLM (`HallucinationsV1Evaluator` y `RubricBasedFinalResponseQualityV1Evaluator`) reconozcan las herramientas declaradas del agente No-Code.
- **`intermediate_data` (`InvocationEvents`)**: Empaqueta el `FunctionCall(name="vertex_ai_search", args={"query": ...})` junto con el `FunctionResponse` que contiene los pasajes recuperados del Data Store (`sv-tramites-datastore`), permitiendo que tanto `TrajectoryEvaluator` como `HallucinationsV1Evaluator` inspeccionen la traza completa.

#### Los 8 Casos del Golden Dataset del GOES ([`golden_dataset.evalset.json`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/agents/sv_citizen_assistant/golden_dataset.evalset.json))

| ID del Caso (`eval_id`) | Institución | Escenario Evaluado | Uso Esperado de Herramienta |
| :--- | :--- | :--- | :--- |
| `01_renovacion_dui_costo_y_requisitos` | **RNPN** | Renovación de DUI vencido (`$10.31 USD`, `https://www.dui.sv`, Duicentro) | `vertex_ai_search` |
| `02_emision_dui_primera_vez_gratuidad` | **RNPN** | Emisión de DUI por primera vez al cumplir 18 años (**Trámite gratuito `$0.00 USD`**) | `vertex_ai_search` |
| `03_emision_pasaporte_primera_vez_adulto` | **DGME** | Pasaporte ordinario primera vez adulto (`$25.00 USD` en Centroamérica, vigencia 6 años) | `vertex_ai_search` |
| `04_pasaporte_menor_de_edad_autorizacion_padres` | **DGME** | Pasaporte para menor de edad (autorización de ambos padres, acta notarial o poder consular) | `vertex_ai_search` |
| `05_solvencia_antecedentes_penales_en_linea` | **DGCP** | Solvencia de Antecedentes Penales (`$3.00 USD`, Portal Simple.sv) | `vertex_ai_search` |
| `06_renovacion_licencia_conducir_sertracen` | **SERTRACEN / VMT** | Renovación de licencia de conducir (`$49.43 USD`, exámenes visual/médico, cero esquelas pendientes) | `vertex_ai_search` |
| `07_conversacion_multiturno_extravio_dui_y_pasaporte` | **RNPN + DGME** | Conversación multi-turno (2 turnos con sesión persistente): extravío de DUI y pasaporte en el mismo día (`$10.31 + $25.00 = $35.31 USD`) | `vertex_ai_search` (x2) |
| `08_rechazo_tramite_fuera_de_alcance_exoneracion_multa` | **Guardrail VMT** | Solicitud fuera de alcance (borrar multa del sistema / redactar demanda judicial) $\rightarrow$ Rechazo cortés y orientación al VMT/SERTRACEN | Sin llamada a herramienta (`[]`) |

#### Las 4 Métricas Oficiales de `google-adk` ([`eval_config.json`](file:///usr/local/google/home/danielardzmtz/Desktop/github_repos/ge-nocode-cicd/ge-nocode-agents-dev/agents/sv_citizen_assistant/eval_config.json))

1. **`tool_trajectory_avg_score` (Threshold `1.0`, `EXACT`)**: Valida determinísticamente que el agente consulte `vertex_ai_search` en preguntas de trámites (Casos 01–07) y no ejecute búsquedas innecesarias ante solicitudes fuera de alcance (Caso 08).
2. **`final_response_match_v2` (Threshold `0.80`)**: Juez LLM (`gemini-2.5-flash`) que certifica equivalencia semántica y exactitud de montos/requisitos frente a la respuesta de referencia.
3. **`hallucinations_v1` (Threshold `0.85`)**: Evalúa frase por frase que ningún dato entregado al ciudadano contradiga o exceda el documento oficial del Data Store.
4. **`rubric_based_final_response_quality_v1` (Threshold `0.85`)**: Evalúa 3 rúbricas institucionales obligatorias:
   - `exactitud_aranceles_usd`
   - `estructura_institucional_3_partes`
   - `tono_y_guardrails_institucionales`

### 4.4. Revisión HITL en `STG` (`:requestAgentReview`) y Publicación Inmutable en `PRD` (`:publish`)
- **En `STG` (`request-review`)**: Una vez superada la evaluación ADK en Staging, `ge_agent_cli.py request-review` transiciona el agente de `PRIVATE` a `ENABLED` mediante `:requestAgentReview` y actualiza `sharingConfig.scope = RESTRICTED` para que los revisores funcionales del GOES realicen pruebas de aceptación (UAT / HITL).
- **En `PRD` (`publish`)**: Tras la promoción a Producción y el pase del Smoke Test ADK, `ge_agent_cli.py publish` habilita el agente (`ENABLED`), configura `sharingConfig.scope = ALL_USERS` y ejecuta `:publish`, creando una **`AgentRevision` inmutable** (`revisions/{revision_id}`) vinculada en `activeRevision`.

### 4.5. Rollback Inmediato en Producción (`rollback`)
Si se detecta cualquier anomalía en producción, se puede revertir instantáneamente a una revisión inmutable anterior o re-desplegar un commit previo:
```bash
python3 cli/ge_agent_cli.py rollback \
  --vars-file spec_variables.auto.yaml \
  --agent-id 3395946724750775553 \
  --revision-id 14012846407794653890
```

---

## 5. Matriz de Configuración por Ambiente (GitHub Actions y Google Cloud Build)

### 5.1. Variables por Repositorio / Trigger

| Variable (`vars.*` en GitHub / `_VAR` en Cloud Build) | Ambiente `DEV` | Ambiente `STG` | Ambiente `PRD` |
| :--- | :--- | :--- | :--- |
| `ENV` / `_ENV` | `dev` | `stg` | `prd` |
| `TARGET_ENV` / `_TARGET_ENV` | `stg` | `prd` | *(Bloqueado por guard)* |
| `SOURCE_REPO_FN` / `_SOURCE_REPO_FN` | `danielardzmtz01/ge-nocode-agents{-cb}-dev.git` | `danielardzmtz01/ge-nocode-agents{-cb}-stg.git` | *(N/A)* |
| `SOURCE_REPO_SN` / `_SOURCE_REPO_SN` | `ge-nocode-agents{-cb}-dev` | `ge-nocode-agents{-cb}-stg` | *(N/A)* |
| `TARGET_REPO_FN` / `_TARGET_REPO_FN` | `danielardzmtz01/ge-nocode-agents{-cb}-stg.git` | `danielardzmtz01/ge-nocode-agents{-cb}-prd.git` | *(N/A)* |
| `GE_PROJECT_ID` / `_GE_PROJECT_ID` | `goes-ge-{gha\|cb}-dev` | `goes-ge-{gha\|cb}-stg` | `goes-ge-{gha\|cb}-prd` |
| `GE_LOCATION` / `_GE_LOCATION` | `global` | `global` | `global` |
| `GE_ENGINE_ID` / `_GE_ENGINE_ID` | `sv-citizen-engine` | `sv-citizen-engine` | `sv-citizen-engine` |
| `GE_DATA_STORE_ID` / `_GE_DATA_STORE_ID` | `sv-tramites-datastore` | `sv-tramites-datastore` | `sv-tramites-datastore` |
| `GE_SHARING_SCOPE` / `_GE_SHARING_SCOPE` | `PRIVATE` | `RESTRICTED` | `ALL_USERS` |

### 5.2. Secretos y Permisos IAM Requeridos

- **En GitHub Actions (`secrets.*`)**:
  - `TOKEN_USER`: Token de GitHub con permisos `repo` y `workflow` para ejecutar `Send To Next Environment`.
  - `GOOGLE_CREDENTIALS` (o Workload Identity Federation vía `vars.WIF_PROVIDER` + `vars.WIF_SERVICE_ACCOUNT`): Credencial con acceso a Discovery Engine y Vertex AI.
- **En Google Cloud Build (Secret Manager + IAM)**:
  - Secretos en Secret Manager por proyecto (`goes-ge-cb-{dev,stg,prd}`):
    - `github-token-user`: Token de GitHub para que `cloudbuild_deployment_actions.yaml` haga `git push` al repositorio del siguiente ambiente.
    - `ge-adc-credentials`: Credencial con acceso a Discovery Engine (`v1alpha`) y Vertex AI (`aiplatform.googleapis.com`).
  - Roles IAM asignados a las cuentas de servicio de Cloud Build (`{PROJECT_NUMBER}@cloudbuild.gserviceaccount.com` y `{PROJECT_NUMBER}-compute@developer.gserviceaccount.com`):
    - `roles/discoveryengine.admin`
    - `roles/aiplatform.user`
    - `roles/secretmanager.secretAccessor`
    - `roles/storage.admin`
    - `roles/logging.logWriter`
