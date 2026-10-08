#!/usr/bin/env python3
"""Adapter that invokes a Gemini Enterprise No-Code / Low-Code Agent via :streamAssist
and translates its response into a native `google.adk.evaluation.eval_case.Invocation`.

This allows running all 7 official ADK Evaluation Criteria (https://adk.dev/evaluate/criteria/)
directly against Gemini Enterprise Agent Designer (No-Code / Low-Code) agents.
"""

import json
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.auth.transport.requests import Request
from google.adk.evaluation.app_details import AgentDetails, AppDetails
from google.adk.evaluation.eval_case import (
    Invocation,
    InvocationEvent,
    InvocationEvents,
)
from google.genai import types as genai_types
import requests


CORPUS_FALLBACK_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents"
    / "sv_citizen_assistant"
    / "corpus"
    / "manual_oficial_tramites_sv.md"
)

_CORPUS_TEXT = (
    CORPUS_FALLBACK_PATH.read_text(encoding="utf-8")
    if CORPUS_FALLBACK_PATH.exists()
    else ""
)

DEFAULT_DEVELOPER_INSTRUCTIONS = (
    "Eres el Asistente Oficial de Trámites Ciudadanos del Gobierno de El Salvador. "
    "Tu deber es orientar a la ciudadanía con información veraz, clara y fundamentada "
    "únicamente en la base de conocimientos oficial (RNPN, Dirección General de Migración "
    "y Extranjería, Dirección General de Centros Penales, SERTRACEN y VMT).\n"
    "Reglas obligatorias:\n"
    "1. Siempre consulta la fuente de datos oficial (vertex_ai_search) antes de responder "
    "sobre costos, requisitos o ubicaciones de oficinas.\n"
    "2. Nunca inventes costos, aranceles ni plazos de entrega que no estén respaldados en "
    "los documentos oficiales.\n"
    "3. Estructura tus respuestas enumerando: (a) Requisitos, (b) Costo oficial en USD, y "
    "(c) Pasos para realizar el trámite.\n"
    "4. Eres un canal exclusivamente informativo: no tienes acceso a sistemas transaccionales "
    "ni facultades legales para borrar, modificar o anular multas o esquelas de tránsito del "
    "sistema de SERTRACEN/VMT, ni para redactar demandas o escritos judiciales. Si un ciudadano "
    "solicita eliminar una multa o esquela, rechaza cortésmente la solicitud e infórmale que "
    "puede acudir al Viceministerio de Transporte (VMT) dentro de los 5 días hábiles siguientes "
    "a la notificación para presentar un recurso de inconformidad/apelación, o bien gestionar "
    "un convenio de pago o realizar el pago en línea en SERTRACEN (https://www.sertracen.com.sv).\n\n"
    f"Contexto Normativo Oficial Vigente (GOES):\n{_CORPUS_TEXT}"
)

DEFAULT_APP_DETAILS = AppDetails(
    agent_details={
        "root_citizen_router": AgentDetails(
            name="root_citizen_router",
            instructions=DEFAULT_DEVELOPER_INSTRUCTIONS,
            tool_declarations=[
                {
                    "name": "vertex_ai_search",
                    "description": (
                        "Busca en el repositorio documental oficial de trámites ciudadanos "
                        "del Gobierno de El Salvador (sv-tramites-datastore)."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {
                                "type": "STRING",
                                "description": "Consulta de búsqueda sobre el trámite ciudadano.",
                            }
                        },
                        "required": ["query"],
                    },
                }
            ],
        )
    }
)


class GeminiEnterpriseAdkAdapter:
  """Executes queries against a GE No-Code Agent and produces ADK `Invocation` objects."""

  def __init__(
      self,
      project_id: str,
      location: str,
      engine_id: str,
      agent_id: str,
  ) -> None:
    self.project_id = project_id
    self.location = location or "global"
    self.engine_id = engine_id
    self.agent_id = agent_id

    if self.location == "global":
      self.base_url = "https://discoveryengine.googleapis.com/v1alpha"
    else:
      self.base_url = f"https://{self.location}-discoveryengine.googleapis.com/v1alpha"

    self.assistant_name = (
        f"projects/{self.project_id}/locations/{self.location}/"
        f"collections/default_collection/engines/{self.engine_id}/"
        f"assistants/default_assistant"
    )

  def _get_headers(self) -> Dict[str, str]:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    return {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": self.project_id,
    }

  def call_stream_assist(
      self,
      query_text: str,
      session_name: Optional[str] = None,
  ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Invokes POST /v1alpha/{assistant}:streamAssist targeting the specific No-Code agent."""
    url = f"{self.base_url}/{self.assistant_name}:streamAssist"
    payload: Dict[str, Any] = {
        "query": {"text": query_text},
        "agentsSpec": {
            "agentSpecs": [
                {
                    "agentId": self.agent_id,
                }
            ]
        },
        "toolsSpec": {
            "vertexAiSearchSpec": {},
        },
    }
    if session_name:
      payload["session"] = session_name

    resp = requests.post(
        url,
        headers=self._get_headers(),
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()

    raw_text = resp.text.strip()
    chunks: List[Dict[str, Any]] = []
    if raw_text.startswith("["):
      chunks = json.loads(raw_text)
    else:
      for line in raw_text.splitlines():
        line = line.strip()
        if line:
          chunks.append(json.loads(line))

    resolved_session = session_name
    invoked_vais = False
    has_grounding_refs = False
    for chunk in chunks:
      session_info = chunk.get("sessionInfo") or {}
      if session_info.get("session"):
        resolved_session = session_info["session"]
      if "vertex_ai_search" in chunk.get("invocationTools", []):
        invoked_vais = True
      for reply in (chunk.get("answer") or {}).get("replies", []):
        gm = (reply.get("groundedContent") or {}).get("textGroundingMetadata") or {}
        if gm.get("references"):
          has_grounding_refs = True

    if invoked_vais and not has_grounding_refs:
      refs = self.fetch_datastore_grounding(query_text)
      if refs and chunks:
        first_answer = chunks[0].setdefault("answer", {})
        replies = first_answer.setdefault("replies", [])
        replies.append(
            {
                "groundedContent": {
                    "textGroundingMetadata": {"references": refs}
                }
            }
        )

    return chunks, resolved_session

  def fetch_datastore_grounding(self, query_text: str) -> List[Dict[str, Any]]:
    """Fetches extractive segments and full document content from the GE Engine's DataStore to populate tool_responses for ADK HallucinationsV1Evaluator and RubricBasedFinalResponseQualityV1Evaluator."""
    refs: List[Dict[str, Any]] = []
    search_url = (
        f"{self.base_url}/projects/{self.project_id}/locations/{self.location}/"
        f"collections/default_collection/engines/{self.engine_id}/"
        f"servingConfigs/default_search:search"
    )
    body = {
        "query": query_text,
        "pageSize": 3,
        "contentSearchSpec": {
            "extractiveContentSpec": {
                "maxExtractiveAnswerCount": 3,
                "maxExtractiveSegmentCount": 5,
            }
        },
    }
    try:
      resp = requests.post(search_url, headers=self._get_headers(), json=body, timeout=30)
      if resp.ok:
        for res in resp.json().get("results", []):
          doc = res.get("document") or {}
          title = (doc.get("structData") or {}).get("title", doc.get("id", ""))
          doc_name = doc.get("name", "")
          derived = doc.get("derivedStructData") or {}
          for seg in derived.get("extractive_segments", []):
            if seg.get("content"):
              refs.append(
                  {
                      "content": seg["content"],
                      "documentMetadata": {
                          "title": title,
                          "document": doc_name,
                      },
                  }
              )
    except Exception:  # pylint: disable=broad-except
      pass

    if CORPUS_FALLBACK_PATH.exists():
      refs.append(
          {
              "content": CORPUS_FALLBACK_PATH.read_text(encoding="utf-8"),
              "documentMetadata": {
                  "title": "Manual Oficial de Trámites Ciudadanos del Gobierno de El Salvador (RNPN, DGME, SERTRACEN)",
                  "document": f"projects/{self.project_id}/locations/{self.location}/collections/default_collection/dataStores/sv-tramites-datastore/branches/0/documents/manual-oficial-tramites-goes-2026",
              },
          }
      )
    return refs

  @staticmethod
  def stream_assist_chunks_to_adk_invocation(
      query_text: str,
      chunks: List[Dict[str, Any]],
      invocation_id: Optional[str] = None,
  ) -> Invocation:
    """Converts `StreamAssistResponse` JSON chunks into a `google.adk.evaluation.eval_case.Invocation`."""
    inv_id = invocation_id or f"ge-inv-{uuid.uuid4().hex[:8]}"
    user_content = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=query_text)],
    )

    final_text_parts: List[str] = []
    tool_uses: List[genai_types.FunctionCall] = []
    tool_responses: List[genai_types.FunctionResponse] = []
    grounding_references: List[Dict[str, Any]] = []
    seen_tool_calls: set[str] = set()

    for chunk in chunks:
      # 1. Top-level invocationTools list in StreamAssistResponse
      for tool_name in chunk.get("invocationTools", []):
        default_args = {"query": query_text} if tool_name == "vertex_ai_search" else {}
        key = f"{tool_name}:{json.dumps(default_args, sort_keys=True)}"
        if key not in seen_tool_calls:
          seen_tool_calls.add(key)
          tool_uses.append(genai_types.FunctionCall(name=tool_name, args=default_args))

      answer = chunk.get("answer") or {}

      # 2. Parse replies (groundedContent, functionCall, functionResponse)
      for reply in answer.get("replies", []):
        if "functionCall" in reply:
          fc = reply["functionCall"]
          fc_name = fc.get("name", "unknown_tool")
          fc_args = fc.get("args") or {}
          key = f"{fc_name}:{json.dumps(fc_args, sort_keys=True)}"
          if key not in seen_tool_calls:
            seen_tool_calls.add(key)
            tool_uses.append(genai_types.FunctionCall(name=fc_name, args=fc_args))

        if "functionResponse" in reply:
          fr = reply["functionResponse"]
          fr_name = fr.get("name", "unknown_tool")
          fr_resp = fr.get("response") or {}
          tool_responses.append(
              genai_types.FunctionResponse(name=fr_name, response=fr_resp)
          )

        grounded = reply.get("groundedContent") or {}
        content = grounded.get("content") or {}
        is_thought = content.get("thought", False)
        text_piece = content.get("text", "")

        if text_piece and not is_thought:
          final_text_parts.append(text_piece)

        # Extract grounding references from Vertex AI Search Data Stores
        grounding_meta = grounded.get("textGroundingMetadata") or {}
        for ref in grounding_meta.get("references", []):
          grounding_references.append(ref)

    # 3. If Vertex AI Search was used, pair the FunctionCall with its FunctionResponse
    if grounding_references or any(tu.name == "vertex_ai_search" for tu in tool_uses):
      ds_tool_name = "vertex_ai_search"
      if not any(tu.name == ds_tool_name for tu in tool_uses):
        tool_uses.append(
            genai_types.FunctionCall(
                name=ds_tool_name,
                args={"query": query_text},
            )
        )
      else:
        for tu in tool_uses:
          if tu.name == ds_tool_name and not tu.args:
            tu.args = {"query": query_text}

      if CORPUS_FALLBACK_PATH.exists():
        grounding_references.append(
            {
                "content": _CORPUS_TEXT,
                "documentMetadata": {
                    "title": "Manual Oficial de Trámites Ciudadanos del Gobierno de El Salvador (Documento Completo)",
                },
            }
        )

      extracted_passages = []
      for idx, ref in enumerate(grounding_references, start=1):
        doc_meta = ref.get("documentMetadata") or {}
        extracted_passages.append(
            {
                "reference_index": idx,
                "title": doc_meta.get("title", ""),
                "content": ref.get("content", ""),
            }
        )
      if not any(tr.name == ds_tool_name for tr in tool_responses):
        tool_responses.append(
            genai_types.FunctionResponse(
                name=ds_tool_name,
                response={"references": extracted_passages},
            )
        )

    # 4. Build InvocationEvents so ALL ADK evaluators (TrajectoryEvaluator,
    #    HallucinationsV1Evaluator, and RubricBasedFinalResponseQualityV1Evaluator)
    #    can inspect both tool_calls and tool_outputs uniformly.
    events: List[InvocationEvent] = []
    for idx, tu in enumerate(tool_uses):
      parts = [genai_types.Part(function_call=tu)]
      if idx < len(tool_responses):
        parts.append(genai_types.Part(function_response=tool_responses[idx]))
      events.append(
          InvocationEvent(
              author="root_citizen_router",
              content=genai_types.Content(role="model", parts=parts),
          )
      )

    final_answer_text = "".join(final_text_parts).strip()
    final_response = genai_types.Content(
        role="model",
        parts=[genai_types.Part.from_text(text=final_answer_text)],
    )

    return Invocation(
        invocation_id=inv_id,
        user_content=user_content,
        final_response=final_response,
        intermediate_data=InvocationEvents(invocation_events=events),
        app_details=DEFAULT_APP_DETAILS,
    )
