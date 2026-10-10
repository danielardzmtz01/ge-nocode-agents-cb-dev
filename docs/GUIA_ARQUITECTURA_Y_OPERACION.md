# Documentación Técnica y Operativa: CI/CD In-Place (`dev` $\rightarrow$ `stg` $\rightarrow$ `prd`), Integración IaC (Terraform) y Evaluación Automatizada (`google-adk`) para Agentes No-Code en Gemini Enterprise (GOES)

> [!IMPORTANT]
> **Resumen Ejecutivo**: Esta documentación describe la arquitectura, el modelo de gobierno, la integración con Infraestructura como Código (Terraform) y la implementación en vivo de **Integración, Evaluación Continua (`google-adk`) y Promoción In-Place Multi-Repositorio (`dev` $\rightarrow$ `stg` $\rightarrow$ `prd`)** para agentes **No-Code / Low-Code** creados en **Gemini Enterprise (Agent Designer)** para el **Gobierno de El Salvador (GOES)**. Incluye dos implementaciones completas con autenticación **100% Keyless** desplegadas y certificadas en vivo dentro de la carpeta de Google Cloud **`GOES` (`folders/402619928367`)**:
> 1. **Opción A — GitHub Actions (Keyless WIF OIDC)**: 3 repositorios (`ge-nocode-agents-{dev,stg,prd}`) desplegados contra 3 proyectos GCP (`goes-ge-gha-{dev,stg,prd}`).
> 2. **Opción B — Google Cloud Build (Attached Service Account)**: 3 repositorios (`ge-nocode-agents-cb-{dev,stg,prd}`) desplegados y promovidos con Cloud Build contra 3 proyectos GCP (`goes-ge-cb-{dev,stg,prd}`).
>
> Para replicar esta solución paso a paso desde cero en la organización de GOES, consulta también **[`docs/GUIA_REPLICACION_GOES.md`](GUIA_REPLICACION_GOES.md)**.

---

## 1. Diagramas de Arquitectura Corporativa (`GitHub Actions` y `Google Cloud Build`)

Ambos flujos siguen el patrón **In-Place Multi-Repositorio (`Send To Next Environment`)**, donde los 3 repositorios (`dev`, `stg`, `prd`) mantienen **exactamente el mismo código fuente** sin IDs quemados (*zero hardcoded IDs*). En tiempo de ejecución, el pipeline genera *in-place* el archivo `spec_variables.auto.yaml`:
- En **`DEV`**: extrae y parametriza la definición viva del agente desde Agent Designer UI (`cli/ge_agent_cli.py pull` $\rightarrow$ [`agents/sv_citizen_assistant/agent_template.json`](../agents/sv_citizen_assistant/agent_template.json)) y ejecuta la compuerta de calidad con **`google-adk`** ([`eval/run_eval.py`](../eval/run_eval.py)).
- En **`STG` y `PRD`**: hidrata [`agent_template.json`](../agents/sv_citizen_assistant/agent_template.json), compila el grafo No-Code en Gemini Enterprise (`:deployLowCode`), ejecuta las 32 evaluaciones de **`google-adk`** y aplica la gobernanza del ambiente (`:requestAgentReview` con alcance `RESTRICTED` en `STG`; `:publish` creando una `AgentRevision` inmutable con alcance `ALL_USERS` en `PRD`).

### Opción A: Arquitectura CI/CD In-Place con GitHub Actions (`goes-ge-gha-{dev,stg,prd}`)

```mermaid
flowchart TD
    subgraph SG_Design["1. Diseño & Exportación (UI a GitOps)"]
        direction LR
        Designer["Diseñador de Agentes<br/>(Gobierno de El Salvador)"]:::gcpBlue
        GE_UI["GE Agent Designer UI<br/>(No-Code / Low-Code en DEV)"]:::gcpBlue
        Pull_CLI["ge_agent_cli.py pull<br/>(GetAgent + Parametrización)"]:::gcpBlue
        Designer --> GE_UI --> Pull_CLI
    end

    Pull_CLI --> Repo_Dev

    subgraph SG_Dev["2. Ambiente DEV (Folder GOES: goes-ge-gha-dev | ge-nocode-agents-dev)"]
        direction LR
        Repo_Dev["Repo GitHub DEV<br/>(agent_template.json + EvalSet)"]:::gcpBlue
        TF_Dev["IaC: Terraform Projects & Services<br/>(Bucket + DataStore + GE Workaround)"]:::gcpBlue
        GE_Dev["Fase 1 (DEV): ge_agent_cli.py pull<br/>(Verifica Agente No-Code PRIVATE)"]:::gcpBlue
        ADK_Dev["Fase 2: Adapter :streamAssist -> ADK<br/>(8 Casos x 4 Métricas = 32 Evals)"]:::gcpGreen
        Repo_Dev --> TF_Dev --> GE_Dev --> ADK_Dev
    end

    ADK_Dev ==>|"Score >= Threshold (32/32 PASSED)<br/>Send To Next Environment"| Repo_Stg

    subgraph SG_Stg["3. Ambiente STG + Revisión HITL (Folder GOES: goes-ge-gha-stg | ge-nocode-agents-stg)"]
        direction LR
        Repo_Stg["Repo GitHub STG<br/>(Promoción In-Place main)"]:::gcpYellow
        TF_Stg["IaC: Terraform Services<br/>(Reconciliación en goes-ge-gha-stg)"]:::gcpYellow
        GE_Stg["Fase 1 (CD): ge_agent_cli.py push<br/>(Hidrata + :deployLowCode)"]:::gcpYellow
        HITL["Fase 2: ADK Gate (32/32) + HITL<br/>(:requestAgentReview | RESTRICTED)"]:::gcpYellow
        Repo_Stg --> TF_Stg --> GE_Stg --> HITL
    end

    HITL ==>|"Aprobación HITL<br/>Send To Next Environment"| Repo_Prd

    subgraph SG_Prd["4. Ambiente PRD & Gobernanza (Folder GOES: goes-ge-gha-prd | ge-nocode-agents-prd)"]
        direction LR
        Repo_Prd["Repo GitHub PRD<br/>(Guard: !contains(prd))"]:::gcpGreen
        TF_Prd["IaC: Terraform Services<br/>(Reconciliación en goes-ge-gha-prd)"]:::gcpGreen
        GE_Prd["Fase 1 (CD): ge_agent_cli.py push<br/>(:deployLowCode + Smoke Test ADK)"]:::gcpGreen
        Pub_Prd["Fase 2: Release Inmutable<br/>(:publish + activeRevision ALL_USERS)"]:::gcpRed
        Repo_Prd --> TF_Prd --> GE_Prd --> Pub_Prd
    end

    classDef gcpBlue fill:#E8F0FE,stroke:#1967D2,stroke-width:2px,color:#000;
    classDef gcpGreen fill:#E6F4EA,stroke:#1E8E3E,stroke-width:2px,color:#000;
    classDef gcpYellow fill:#FEF7E0,stroke:#B06000,stroke-width:2px,color:#000;
    classDef gcpRed fill:#FCE8E6,stroke:#D93025,stroke-width:2px,color:#000;
```

### Opción B: Arquitectura CI/CD In-Place con Google Cloud Build (`goes-ge-cb-{dev,stg,prd}`)

```mermaid
flowchart TD
    subgraph SG_Design["1. Diseño & Exportación (UI a GitOps)"]
        direction LR
        Designer["Diseñador de Agentes<br/>(Gobierno de El Salvador)"]:::gcpBlue
        GE_UI["GE Agent Designer UI<br/>(No-Code / Low-Code en DEV)"]:::gcpBlue
        Pull_CLI["ge_agent_cli.py pull<br/>(GetAgent + Parametrización)"]:::gcpBlue
        Designer --> GE_UI --> Pull_CLI
    end

    Pull_CLI --> Repo_Dev

    subgraph SG_Dev["2. Proyecto GCP DEV (Folder GOES: goes-ge-cb-dev | ge-nocode-agents-cb-dev)"]
        direction LR
        Repo_Dev["Repo GitHub DEV<br/>(ge-nocode-agents-cb-dev)"]:::gcpBlue
        CB_Deploy_Dev["Cloud Build (SA ge-cicd-runner)<br/>(cloudbuild_deploy_and_eval.yaml)"]:::gcpBlue
        GE_Dev["Gemini Enterprise DEV<br/>(pull + :streamAssist ADK Gate 32/32)"]:::gcpGreen
        SM_Dev["Secret Manager<br/>(github-token-user)"]:::gcpBlue
        CB_Promo_Dev["Cloud Build Promote<br/>(cloudbuild_deployment_actions.yaml)"]:::gcpBlue
        Repo_Dev --> CB_Deploy_Dev --> GE_Dev --> CB_Promo_Dev
        SM_Dev -.->|"Inyecta secretEnv"| CB_Promo_Dev
    end

    CB_Promo_Dev ==>|"git push target-repo main --force<br/>(Promoción DEV -> STG)"| Repo_Stg

    subgraph SG_Stg["3. Proyecto GCP STG + Aprobación HITL (Folder GOES: goes-ge-cb-stg | ge-nocode-agents-cb-stg)"]
        direction LR
        Repo_Stg["Repo GitHub STG<br/>(ge-nocode-agents-cb-stg)"]:::gcpYellow
        CB_Deploy_Stg["Cloud Build (SA ge-cicd-runner)<br/>(cloudbuild_deploy_and_eval.yaml)"]:::gcpYellow
        GE_Stg["Gemini Enterprise STG<br/>(:deployLowCode + ADK + :requestAgentReview)"]:::gcpYellow
        HITL_Stg["Aprobación HITL<br/>(Cloud Build Approval Gate + RESTRICTED)"]:::gcpYellow
        CB_Promo_Stg["Cloud Build Promote<br/>(cloudbuild_deployment_actions.yaml)"]:::gcpYellow
        Repo_Stg --> CB_Deploy_Stg --> GE_Stg --> HITL_Stg --> CB_Promo_Stg
    end

    CB_Promo_Stg ==>|"git push target-repo main --force<br/>(Promoción STG -> PRD)"| Repo_Prd

    subgraph SG_Prd["4. Proyecto GCP PRD & Gobernanza (Folder GOES: goes-ge-cb-prd | ge-nocode-agents-cb-prd)"]
        direction LR
        Repo_Prd["Repo GitHub PRD<br/>(ge-nocode-agents-cb-prd)"]:::gcpGreen
        CB_Deploy_Prd["Cloud Build (SA ge-cicd-runner)<br/>(cloudbuild_deploy_and_eval.yaml)"]:::gcpGreen
        GE_Prd["Gemini Enterprise PRD<br/>(:deployLowCode + Smoke Test ADK)"]:::gcpGreen
        Pub_Prd["Release Inmutable Ciudadano<br/>(:publish + activeRevision ALL_USERS)"]:::gcpRed
        Logs_Prd["Cloud Logging<br/>(CLOUD_LOGGING_ONLY + Auditoría ADK)"]:::gcpBlue
        Repo_Prd --> CB_Deploy_Prd --> GE_Prd --> Pub_Prd
        CB_Deploy_Prd -.->|"Trazabilidad"| Logs_Prd
    end

    classDef gcpBlue fill:#E8F0FE,stroke:#1967D2,stroke-width:2px,color:#000;
    classDef gcpGreen fill:#E6F4EA,stroke:#1E8E3E,stroke-width:2px,color:#000;
    classDef gcpYellow fill:#FEF7E0,stroke:#B06000,stroke-width:2px,color:#000;
    classDef gcpRed fill:#FCE8E6,stroke:#D93025,stroke-width:2px,color:#000;
```

---

## 2. Inventario de Recursos Desplegados en Vivo (`folders/402619928367` — `GOES`)

Todos los recursos fueron aprovisionados dentro de la carpeta **`GOES` (`folders/402619928367`)** en la organización `danielardzmtz.altostrat.com` (`298580255441`), con estado remoto de Terraform centralizado en el bucket `gs://goes-ge-tf-backend` (`drm-tfproject-000`). Cada uno de los 6 proyectos cuenta con:
- **Licenciamiento Gemini Enterprise**: `LicenseConfig` (`SUBSCRIPTION_TIER_SEARCH_AND_ASSISTANT`), `UserStore` (`default_user_store` con `enableLicenseAutoRegister: true`).
- **Vertex AI Search Data Store (RAG)**: `sv-tramites-datastore` con el documento normativo indexado `manual-oficial-tramites-goes-2026` (*RNPN, DGME, Centros Penales, SERTRACEN y VMT*).
- **Gemini Enterprise Engine & Assistant**: `sv-citizen-engine` (`SOLUTION_TYPE_SEARCH`, `APP_TYPE_INTRANET`, `SEARCH_TIER_ENTERPRISE`, `SEARCH_ADD_ON_LLM`) + `assistants/default_assistant`.
- **Service Account dedicada de CI/CD**: `ge-cicd-runner@{PROJECT_ID}.iam.gserviceaccount.com`.

### 2.1. Ejemplo 1: Flujo Multi-Repo con **GitHub Actions** (`goes-ge-gha-{dev,stg,prd}`)

| Ambiente | Repositorio GitHub | Proyecto GCP (`folders/402619928367`) | Project Number | Agent ID en GE | Estado / Sharing Scope | Active Revision (`:publish`) | Ejecución Certificada |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`DEV`** | `danielardzmtz01/ge-nocode-agents-dev` | `goes-ge-gha-dev` | `1076809815833` | `2172421677339450929` | `PRIVATE` / `ENABLED` | `5074119707885744899` | `ge_agent_deploy_and_eval.yml` (`32/32 PASSED`) $\rightarrow$ `deployment_actions.yml` (`DEV -> STG`) |
| **`STG`** | `danielardzmtz01/ge-nocode-agents-stg` | `goes-ge-gha-stg` | `345628853626` | `11971858956007198093` | `ENABLED` / `RESTRICTED` (`:requestAgentReview`) | — | `ge_agent_deploy_and_eval.yml` (`32/32 PASSED`) $\rightarrow$ `deployment_actions.yml` (`STG -> PRD`) |
| **`PRD`** | `danielardzmtz01/ge-nocode-agents-prd` | `goes-ge-gha-prd` | `30228259118` | `3395946724750775553` | `ENABLED` / `ALL_USERS` (`:publish`) | **`14012846407794653890`** | `ge_agent_deploy_and_eval.yml` (`32/32 PASSED` + Revisión Inmutable) |

### 2.2. Ejemplo 2: Flujo Multi-Repo con **Google Cloud Build** (`goes-ge-cb-{dev,stg,prd}`)

| Ambiente | Repositorio GitHub | Proyecto GCP (`folders/402619928367`) | Project Number | Agent ID en GE | Estado / Sharing Scope | Active Revision (`:publish`) | Triggers & Builds en Cloud Build |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`DEV`** | `danielardzmtz01/ge-nocode-agents-cb-dev` | `goes-ge-cb-dev` | `601937217732` | `14529129893765249992` | `PRIVATE` / `PRIVATE` | — | Trigger: `ge-nocode-agent-deploy-eval-dev`<br>Promote: `ge-nocode-promote-dev-to-stg` |
| **`STG`** | `danielardzmtz01/ge-nocode-agents-cb-stg` | `goes-ge-cb-stg` | `425990910052` | `4987620311259970191` | `ENABLED` / `RESTRICTED` (`:requestAgentReview`) | — | Trigger: `ge-nocode-agent-deploy-eval-stg`<br>Promote: `ge-nocode-promote-stg-to-prd` |
| **`PRD`** | `danielardzmtz01/ge-nocode-agents-cb-prd` | `goes-ge-cb-prd` | `1068386666374` | `3632113936026526418` | `ENABLED` / `ALL_USERS` (`:publish`) | **`8793931032536939173`** | Trigger: `ge-nocode-agent-deploy-eval-prd` (`32/32 PASSED` + `:publish`) |

---

## 3. Estructura del Código y Componentes Clave

```text
.
├── .github/workflows/                         # OPCIÓN A: Pipelines de GitHub Actions (Keyless WIF)
│   ├── ge_agent_deploy_and_eval.yml           # Hidrata spec_variables.auto.yaml, ejecuta pull (DEV) o push+:deployLowCode (STG/PRD), evalúa con ADK y gobierna estado
│   ├── deployment_actions.yml                 # "Send To Next Environment" (clona SOURCE_REPO_FN y hace push a TARGET_REPO_FN)
│   ├── terraform_projects.yml                 # Aprovisiona División 1 (Landing Zone: Folder GOES, Proyectos, APIs, SAs, WIF, Secret Manager)
│   ├── terraform_services.yml                 # Aprovisiona División 3 (Bucket Corpus, DataStore Nativo y Workaround v1alpha)
│   └── reset_environment.yml                  # Elimina el agente custom del ambiente actual para reiniciar demostraciones en vivo
├── cloudbuild/                                # OPCIÓN B: Pipelines de Google Cloud Build (SA ge-cicd-runner)
│   ├── cloudbuild_deploy_and_eval.yaml        # Pipeline equivalente en Cloud Build con cuenta de servicio adjunta y CLOUD_LOGGING_ONLY
│   └── cloudbuild_deployment_actions.yaml     # Promoción In-Place (DEV -> STG -> PRD) desde Cloud Build usando Secret Manager (github-token-user)
├── terraform_projects/                        # IaC División 1: Landing Zone Corporativa
│   ├── provider.tf
│   ├── variables.tf
│   ├── folders.tf
│   └── projects.tf
├── terraform_services/                        # IaC División 3: Servicios de Gemini Enterprise por Ambiente
│   ├── provider.tf
│   ├── variables.tf
│   ├── main.tf
│   └── outputs.tf
├── cli/
│   ├── ensure_ge_infra.py                     # Reconciliador idempotente invocado por terraform_data (create y --destroy)
│   ├── ge_agent_cli.py                        # CLI GitOps: pull, push (:deployLowCode), request-review, publish (:publish), rollback y delete
│   └── refresh_credentials_and_reset_demo.py  # Script auxiliar para verificar el bucket de estado remoto y limpiar STG/PRD
├── eval/
│   ├── ge_adk_adapter.py                      # Invoca :streamAssist en GE y traduce la respuesta a google.adk.evaluation.eval_case.Invocation
│   └── run_eval.py                            # Ejecuta el Golden Dataset concurrentemente con los 4 evaluadores oficiales de google-adk
├── agents/
│   └── sv_citizen_assistant/
│       ├── agent_template.json                # Definición declarativa del Agente No-Code con placeholders (${ENV}, ${GE_PROJECT_ID}, ...)
│       ├── eval_config.json                   # Umbrales y rúbricas oficiales de google-adk
│       ├── golden_dataset.evalset.json        # 8 casos del Golden Dataset del Gobierno de El Salvador (formato ADK EvalSet)
│       └── corpus/
│           └── manual_oficial_tramites_sv.md  # Corpus normativo oficial indexado en sv-tramites-datastore
└── docs/
    ├── GUIA_ARQUITECTURA_Y_OPERACION.md       # Manual técnico detallado en el repositorio
    ├── GUIA_REPLICACION_GOES.md               # Guía paso a paso para replicación por el equipo del GOES
    └── diagrams/                              # Diagramas Mermaid (.mmd) de GitHub Actions y Cloud Build
```

---

## 4. Funcionamiento Interno del Ciclo de Vida del Agente No-Code en Discovery Engine `v1alpha`

### 4.1. Creación Visual y Extracción Parametrizada (`pull` en `DEV`)
1. Un diseñador funcional crea o ajusta el agente en la consola visual **Gemini Enterprise Agent Designer** en el proyecto `DEV`.
2. Ejecuta [`cli/ge_agent_cli.py`](../cli/ge_agent_cli.py) con el subcomando `pull` (o se ejecuta automáticamente como Fase 1 del pipeline en `DEV`):
   ```bash
   python3 cli/ge_agent_cli.py pull \
     --project-id goes-ge-gha-dev \
     --location global \
     --engine-id sv-citizen-engine \
     --agent-id 2172421677339450929 \
     --data-store-id sv-tramites-datastore \
     --template-path agents/sv_citizen_assistant/agent_template.json
   ```
3. El comando `pull` elimina metadatos efímeros de solo lectura (`name`, `state`, `createTime`, `updateTime`, `failureReason`, `agentIdentityInfo`, `observabilityConfig`, `deployedNodes`, `deployedRootAgentId`) y reemplaza automáticamente el ID/número de proyecto, ubicación, Engine ID, Data Store ID, sufijo `(${ENV})` y alcance por placeholders (`${ENV}`, `${GE_PROJECT_ID}`, `${GE_LOCATION}`, `${GE_ENGINE_ID}`, `${GE_DATA_STORE_ID}`, `${GE_SHARING_SCOPE}`).

### 4.2. Hidratación In-Place y Compilación ADK Gestionada (`push` + `:deployLowCode` en `STG` / `PRD`)
1. En tiempo de ejecución, el pipeline crea `spec_variables.auto.yaml` con los valores del ambiente activo (`dev`, `stg` o `prd`).
2. `ge_agent_cli.py push` hidrata [`agents/sv_citizen_assistant/agent_template.json`](../agents/sv_citizen_assistant/agent_template.json) y resuelve dinámicamente el **`project_number` numérico** consultando el recurso del asistente en Discovery Engine para normalizar `lowCodeAgentDefinition.nodes[*].llmAgentNode.dataStoreSpecs.specs[*].dataStore` (requisito estricto del compilador interno de Discovery Engine).
3. Invoca `CreateAgent` (`POST .../agents`) si el agente aún no existe en el ambiente destino, o `UpdateAgent` (`PATCH .../agents/{id}?updateMask=displayName,description,lowCodeAgentDefinition`) si ya existe.
4. Invoca el endpoint de compilación:
   ```http
   POST https://discoveryengine.googleapis.com/v1alpha/{agent_name}:deployLowCode
   {
     "name": "projects/{project_number}/locations/global/collections/default_collection/engines/sv-citizen-engine/assistants/default_assistant/agents/{agent_id}",
     "deployMode": "DEPLOY"
   }
   ```

### 4.3. Adaptador `:streamAssist` $\rightarrow$ `google-adk` y Compuerta de Calidad ([`eval/run_eval.py`](../eval/run_eval.py))
Dado que los agentes No-Code viven dentro del runtime gestionado de Gemini Enterprise y se consumen por `POST /v1alpha/{assistant}:streamAssist`, el adaptador de solo lectura [`eval/ge_adk_adapter.py`](../eval/ge_adk_adapter.py) construye objetos nativos `google.adk.evaluation.eval_case.Invocation` compatibles con todos los evaluadores oficiales de `google-adk`:
- **`app_details` (`AppDetails`)**: Lee dinámicamente las instrucciones del nodo raíz (`root_citizen_router`) desde la plantilla o desde `GET /v1alpha/{agent_name}` junto con el corpus documental y declara formalmente la herramienta `vertex_ai_search` para que los jueces LLM (`HallucinationsV1Evaluator` y `RubricBasedFinalResponseQualityV1Evaluator`) evalúen con contexto completo.
- **`intermediate_data` (`InvocationEvents`)**: Empaqueta el `FunctionCall(name="vertex_ai_search", args={"query": ...})` junto con el `FunctionResponse` que contiene los pasajes recuperados del Data Store (`sv-tramites-datastore`), permitiendo que tanto `TrajectoryEvaluator` como `HallucinationsV1Evaluator` inspeccionen la traza completa.

#### Los 8 Casos del Golden Dataset del GOES ([`agents/sv_citizen_assistant/golden_dataset.evalset.json`](../agents/sv_citizen_assistant/golden_dataset.evalset.json))

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

#### Las 4 Métricas Oficiales de `google-adk` ([`agents/sv_citizen_assistant/eval_config.json`](../agents/sv_citizen_assistant/eval_config.json))

1. **`tool_trajectory_avg_score` (Threshold `1.0`, `match_type: "IN_ORDER"`)**: Valida determinísticamente que el agente consulte `vertex_ai_search` en preguntas de trámites (Casos 01–07) y no ejecute búsquedas innecesarias ante solicitudes fuera de alcance (Caso 08).
2. **`final_response_match_v2` (Threshold `0.80`)**: Juez LLM (`gemini-2.5-flash`) que certifica equivalencia semántica y exactitud de montos/requisitos frente a la respuesta de referencia.
3. **`hallucinations_v1` (Threshold `0.85`)**: Evalúa frase por frase que ningún dato entregado al ciudadano contradiga o exceda el documento oficial del Data Store.
4. **`rubric_based_final_response_quality_v1` (Threshold `0.85`)**: Evalúa 3 rúbricas institucionales obligatorias:
   - `exactitud_aranceles`: Menciona los aranceles o costos oficiales en USD exactamente como aparecen en la fuente oficial.
   - `estructura_clara_requisitos`: Enumera claramente los requisitos documentales y los pasos que debe seguir el ciudadano salvadoreño.
   - `tono_institucional_y_seguridad`: Mantiene un tono institucional, claro, respetuoso, seguro y en español, sin asumir facultades fuera de su alcance informativo.

### 4.4. Revisión HITL en `STG` (`:requestAgentReview`) y Publicación Inmutable en `PRD` (`:publish`)
- **En `STG` (`request-review`)**: Una vez superada la evaluación ADK en Staging, `ge_agent_cli.py request-review` transiciona el agente de `PRIVATE` a `ENABLED` mediante `:requestAgentReview` y actualiza `sharingConfig.scope = RESTRICTED` para que los revisores funcionales del GOES realicen pruebas de aceptación (UAT / HITL).
- **En `PRD` (`publish`)**: Tras la promoción a Producción y el pase del Smoke Test ADK, `ge_agent_cli.py publish` habilita el agente (`ENABLED`), configura `sharingConfig.scope = ALL_USERS` y ejecuta `:publish`, creando una **`AgentRevision` inmutable** (`revisions/{revision_id}`) vinculada en `activeRevision`.

### 4.5. Rollback Inmediato en Producción (`rollback`)
Si se detecta cualquier anomalía en producción, se puede revertir instantáneamente a una revisión inmutable anterior:
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
| `WIF_PROVIDER` | `projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider` | `projects/{PROJECT_NUMBER}/...` | `projects/{PROJECT_NUMBER}/...` |
| `WIF_SERVICE_ACCOUNT` | `ge-cicd-runner@goes-ge-{gha\|cb}-dev.iam.gserviceaccount.com` | `ge-cicd-runner@goes-ge-{gha\|cb}-stg.iam.gserviceaccount.com` | `ge-cicd-runner@goes-ge-{gha\|cb}-prd.iam.gserviceaccount.com` |
| `TF_PROJECT` | `drm-tfproject-000` | `drm-tfproject-000` | `drm-tfproject-000` |
| `BACKEND_BUCKET` | `goes-ge-tf-backend` | `goes-ge-tf-backend` | `goes-ge-tf-backend` |

### 5.2. Autenticación Keyless, Secretos y Permisos IAM Requeridos

- **En GitHub Actions (Keyless WIF + `secrets.TOKEN_USER`)**:
  - **Autenticación hacia GCP**: 100% sin llaves estáticas (*Keyless*) mediante `google-github-actions/auth@v2` usando `vars.WIF_PROVIDER` y `vars.WIF_SERVICE_ACCOUNT` (`ge-cicd-runner@goes-ge-gha-{env}.iam.gserviceaccount.com`).
  - **`secrets.TOKEN_USER`**: Personal Access Token de GitHub con permisos `repo` y `workflow` exclusivamente para que `.github/workflows/deployment_actions.yml` ejecute `Send To Next Environment` (`git push` al repositorio del siguiente ambiente).
- **En Google Cloud Build (Attached Service Account + Secret Manager)**:
  - **Autenticación hacia GCP**: `cloudbuild_deploy_and_eval.yaml` se ejecuta directamente con `serviceAccount: "projects/$PROJECT_ID/serviceAccounts/ge-cicd-runner@$PROJECT_ID.iam.gserviceaccount.com"`.
  - **Secret Manager (`goes-ge-cb-{dev,stg,prd}`)**:
    - `github-token-user`: Token de GitHub inyectado vía `secretEnv` en `cloudbuild_deployment_actions.yaml` para hacer `git push` al repositorio del siguiente ambiente.
- **Roles IAM asignados a `ge-cicd-runner@{PROJECT_ID}.iam.gserviceaccount.com`**:
  - En su respectivo proyecto (`goes-ge-{gha|cb}-{dev,stg,prd}`):
    - `roles/discoveryengine.admin`
    - `roles/aiplatform.user`
    - `roles/storage.admin`
    - `roles/serviceusage.serviceUsageAdmin`
    - `roles/secretmanager.secretAccessor`
    - `roles/cloudbuild.builds.editor`
    - `roles/iam.serviceAccountUser`
    - `roles/logging.logWriter`
  - Sobre el bucket centralizado de estado de Terraform (`gs://goes-ge-tf-backend` en `drm-tfproject-000`):
    - `roles/storage.admin`

---

## 6. Integración con IaC Corporativo (Terraform + Workaround `v1alpha`)

Siguiendo el estándar corporativo de repositorios de infraestructura (`terraform_projects/` + `terraform_services/`), cada repositorio de ambiente (`dev`, `stg`, `prd`) incluye el código declarativo de Terraform y lo conecta con el ciclo de vida del agente No-Code:

| División | Directorio / Workflow | Qué es Nativo en Terraform vs. Workaround `v1alpha` | Cómo se conecta con el Agente No-Code |
| :--- | :--- | :--- | :--- |
| **1. Landing Zone Corporativa** | [`terraform_projects/`](../terraform_projects/) + [`.github/workflows/terraform_projects.yml`](../.github/workflows/terraform_projects.yml) | **100% Nativo en Terraform**: `google_folder` (`GOES`), `google_project` (los proyectos por ambiente), `google_project_service` (APIs), `google_service_account` (`ge-cicd-runner`), `google_project_iam_member`, `google_iam_workload_identity_pool`, `google_iam_workload_identity_pool_provider` y `google_secret_manager_secret`. Estado remoto en `gs://goes-ge-tf-backend` (`${ENV}/projects/terraform/state`). | Prepara el entorno seguro por ambiente (`dev`, `stg`, `prd`) y la federación de identidad OIDC donde correrán los pipelines. |
| **2. Repositorios y Variables** | 6 Repositorios en GitHub (`ge-nocode-agents-{dev,stg,prd}` y `ge-nocode-agents-cb-{dev,stg,prd}`) | **Configuración GitOps por Ambiente**: Variables (`ENV`, `GE_PROJECT_ID`, `GE_ENGINE_ID`, `GE_DATA_STORE_ID`, `GE_SHARING_SCOPE`, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `TF_PROJECT`, `BACKEND_BUCKET`, `TARGET_ENV`, `TARGET_REPO_FN`) y Secreto (`TOKEN_USER`). | Inyecta en tiempo de ejecución las variables en `spec_variables.auto.tfvars` (para Terraform) y `spec_variables.auto.yaml` (para el CLI del Agente). |
| **3. Servicios Gemini Enterprise** | [`terraform_services/`](../terraform_services/) + [`.github/workflows/terraform_services.yml`](../.github/workflows/terraform_services.yml) + [`cli/ensure_ge_infra.py`](../cli/ensure_ge_infra.py) | **Híbrido (Nativo + Workaround Declarativo)**:<br>• **Nativo**: `google_storage_bucket` (bucket del corpus), `google_storage_bucket_object` (`manual_oficial_tramites_sv.md`) y `google_discovery_engine_data_store` (`sv-tramites-datastore`).<br>• **Workaround (`terraform_data.gemini_enterprise_engine_and_corpus`)**: Ejecuta `local-exec` (`python3 cli/ensure_ge_infra.py`) con trigger `filemd5(corpus)` en `create` y `--destroy` en `destroy` para reconciliar idempotentemente en la API `v1alpha`: `LicenseConfig`, `UserStore`, el documento RAG indexado, el `Engine` (`APP_TYPE_INTRANET` + `SEARCH_ADD_ON_LLM`) y el `default_assistant`. Estado remoto en `gs://goes-ge-tf-backend` (`${ENV}/services/terraform/state`). | Garantiza que el Data Store `sv-tramites-datastore`, el documento normativo y el Engine `sv-citizen-engine` existan antes de desplegar o evaluar el Agente No-Code. |
| **4. Ciclo de Vida del Agente No-Code y Evaluación ADK** | [`cli/ge_agent_cli.py`](../cli/ge_agent_cli.py) + [`eval/run_eval.py`](../eval/run_eval.py) + [`.github/workflows/ge_agent_deploy_and_eval.yml`](../.github/workflows/ge_agent_deploy_and_eval.yml) | **CLI Declarativo REST `v1alpha` + `google-adk`**: Extrae y parametriza desde `DEV` (`pull`), hidrata y compila en `STG`/`PRD` (`push` + `:deployLowCode`), evalúa las 32 métricas con `google-adk` y gobierna el estado (`:requestAgentReview` en STG / `:publish` en PRD). | Garantiza que ningún cambio en la infraestructura RAG ni en el diseño No-Code llegue a producción sin superar el Quality Gate. |

---

## 7. Detalle Paso a Paso del Ciclo de Vida del Agente No-Code ([`cli/ge_agent_cli.py`](../cli/ge_agent_cli.py))

El script [`cli/ge_agent_cli.py`](../cli/ge_agent_cli.py) encapsula las 6 operaciones del ciclo de vida de un agente No-Code / Low-Code sobre la API `v1alpha` de Discovery Engine (`https://discoveryengine.googleapis.com/v1alpha`):

1. **`pull` — Exportación desde Agent Designer UI y Parametrización (`DEV` $\rightarrow$ Git)**:
   - Cuando un diseñador o analista modifica las instrucciones, los *starter prompts* o las herramientas en la consola visual de **Agent Designer (`DEV`)**, ejecuta `python3 cli/ge_agent_cli.py pull` (también ejecutado automáticamente en el pipeline de `DEV`).
   - El CLI invoca `GET /v1alpha/projects/{project}/locations/global/collections/default_collection/engines/{engine}/assistants/default_assistant/agents/{agent_id}`.
   - Limpia los metadatos efímeros de solo lectura (`name`, `state`, `createTime`, `updateTime`, `failureReason`, `agentIdentityInfo`, `observabilityConfig`, `deployedNodes`, `deployedRootAgentId`) y **reemplaza automáticamente todos los IDs de `DEV`** (ID del proyecto, número de proyecto, ubicación, Engine ID, Data Store ID, alcance y sufijo `(${ENV})`) por los placeholders `${GE_PROJECT_ID}`, `${GE_LOCATION}`, `${GE_ENGINE_ID}`, `${GE_DATA_STORE_ID}`, `${GE_SHARING_SCOPE}` y `${ENV}`, guardando [`agents/sv_citizen_assistant/agent_template.json`](../agents/sv_citizen_assistant/agent_template.json).
2. **`push` — Hidratación In-Place y Compilación `:deployLowCode` (Git $\rightarrow$ `STG` / `PRD`)**:
   - Lee `spec_variables.auto.yaml` y sustituye los placeholders en `agent_template.json`.
   - Resuelve dinámicamente el `project_number` numérico del proyecto destino (requerido internamente por el parser de Vertex AI Search en `lowCodeAgentDefinition.nodes[].llmAgentNode.dataStoreSpecs.specs[].dataStore`).
   - Busca por `displayName` (o `agent_id`) si el agente ya existe en el `default_assistant` del ambiente: si no existe ejecuta `POST .../agents` (creación); si ya existe ejecuta `PATCH .../agents/{id}?updateMask=displayName,description,lowCodeAgentDefinition` (actualización idempotente).
   - Finalmente invoca **`POST /v1alpha/{agent_name}:deployLowCode`** con `{"name": agent_name, "deployMode": "DEPLOY"}`, que compila los nodos `lowCodeAgentDefinition` y activa el agente en el motor conversacional.
3. **`request-review` — Solicitud de Revisión Humana HITL (`STG`)**:
   - Tras aprobar las 32 métricas de `google-adk` en `STG`, el pipeline invoca `python3 cli/ge_agent_cli.py request-review`.
   - Ejecuta **`POST /v1alpha/{agent_name}:requestAgentReview`** (transicionando el agente fuera de `PRIVATE` a `ENABLED`) y aplica `PATCH ?updateMask=sharingConfig` con `{"sharingConfig": {"scope": "RESTRICTED"}}`, habilitando el agente para el equipo revisor de QA/Gobernanza antes de autorizar el pase a `PRD`.
4. **`publish` — Revisión Inmutable y Publicación General (`PRD`)**:
   - Tras aprobar el Smoke Test de `google-adk` en `PRD`, el pipeline invoca `python3 cli/ge_agent_cli.py publish`.
   - Asegura que el agente esté en estado `ENABLED`, actualiza su alcance a `sharingConfig.scope = "ALL_USERS"`, e invoca **`POST /v1alpha/{agent_name}:publish`** con la etiqueta del commit (`label: "Automated PRD release from commit ..."`).
   - Esto genera un snapshot inmutable (`AgentRevision`) y actualiza el puntero `activeRevision` del agente productivo.
5. **`rollback` — Reversión Instantánea en Producción (`PRD`)**:
   - Ejecuta **`POST /v1alpha/{agent_name}:rollback`** apuntando a un `revisionId` previo para revertir el agente en segundos sin necesidad de recompilar.
6. **`delete` — Limpieza del Agente Custom para Reinicio de Demos (`STG` / `PRD`)**:
   - Ejecuta `POST :disableAgent` seguido de **`DELETE /v1alpha/{agent_name}`** para dejar los ambientes de `STG` y `PRD` limpios antes de una demostración manual en vivo.

---

## 8. Guía Paso a Paso para Replicación por GOES y Prueba Manual en Vivo

> [!TIP]
> Para el runbook completo de replicación desde cero en la organización de Google Cloud y GitHub del GOES (bootstrap de `terraform_projects`, WIF OIDC, variables `gh variable set`, `terraform_services` y adaptación a nuevas instituciones), consulta **[`docs/GUIA_REPLICACION_GOES.md`](GUIA_REPLICACION_GOES.md)**.

### Ejecución de Prueba Manual en Vivo (`DEV` $\rightarrow$ `STG` $\rightarrow$ `PRD`)

1. **Paso 0 — Reiniciar `STG` y `PRD` antes de una Demo (Opcional)**:
   - Puedes ejecutar desde la pestaña **Actions** el workflow **`Reset Environment Custom Agent`** en `ge-nocode-agents-stg` y `ge-nocode-agents-prd`, o correr localmente:
     ```bash
     python3 cli/refresh_credentials_and_reset_demo.py
     ```
   - Esto verifica el bucket central de estado de Terraform (`gs://goes-ge-tf-backend`), elimina el agente custom de `STG` y `PRD` (dejando únicamente `DEV` activo) y limpia el historial de ejecuciones de `STG` y `PRD`.
2. **Paso 1 — Verificar o Editar el Agente en `DEV` (`goes-ge-gha-dev`)**:
   - Entra a la consola de **Gemini Enterprise $\rightarrow$ Agent Designer** en el proyecto `goes-ge-gha-dev` (`sv-citizen-engine`).
   - Verás el agente **`Asistente de Trámites Ciudadanos - Gobierno de El Salvador (dev)`** (`ID: 2172421677339450929`).
   - En los proyectos `goes-ge-gha-stg` y `goes-ge-gha-prd` comprobarás que el agente custom no existe cuando el entorno está reseteado.
3. **Paso 2 — Promover manualmente de `DEV` a `STG`**:
   - Ve al repositorio **`danielardzmtz01/ge-nocode-agents-dev`** $\rightarrow$ pestaña **Actions** $\rightarrow$ selecciona **`Send To Next Environment`** $\rightarrow$ haz clic en **`Run workflow`** (branch `main`).
   - Abre la pestaña **Actions** del repositorio **`danielardzmtz01/ge-nocode-agents-stg`**: verás iniciarse automáticamente el workflow **`GE No-Code Agent Deploy & ADK Eval Actions`**, ejecutando:
     - **Autenticación Keyless WIF**: OIDC hacia `ge-cicd-runner@goes-ge-gha-stg.iam.gserviceaccount.com`.
     - **Fase 1 (No-Code CD)**: `ge_agent_cli.py push` creando y compilando (`:deployLowCode`) el agente en `goes-ge-gha-stg`.
     - **Fase 2 (ADK Gate + HITL)**: `eval/run_eval.py` validando las 32 métricas (`32/32 PASSED`) y ejecutando `:requestAgentReview` (`RESTRICTED`).
4. **Paso 3 — Promover manualmente de `STG` a `PRD`**:
   - Tras verificar el agente en `STG`, ve al repositorio **`danielardzmtz01/ge-nocode-agents-stg`** $\rightarrow$ pestaña **Actions** $\rightarrow$ selecciona **`Send To Next Environment`** $\rightarrow$ haz clic en **`Run workflow`**.
   - Abre la pestaña **Actions** del repositorio **`danielardzmtz01/ge-nocode-agents-prd`**: verás ejecutarse **`GE No-Code Agent Deploy & ADK Eval Actions`**, que desplegará el agente No-Code en `goes-ge-gha-prd`, validará las 32 métricas con `google-adk` y ejecutará **`:publish`** creando la `AgentRevision` inmutable con alcance `ALL_USERS`.
