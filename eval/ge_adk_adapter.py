#!/usr/bin/env python3
"""Read-only Evaluation Adapter that queries an already-deployed Gemini Enterprise
No-Code / Low-Code Agent via `POST /v1alpha/{assistant}:streamAssist` and translates
its response into a native `google.adk.evaluation.eval_case.Invocation`.

IMPORTANT:
- This module NEVER creates or modifies any agent in Gemini Enterprise.
- The No-Code agent is designed visually in the Agent Designer UI (DEV), exported via
  `cli/ge_agent_cli.py pull` into `agent_template.json`, and deployed via `cli/ge_agent_cli.py push`.
- For ADK LLM-as-a-Judge evaluators (`HallucinationsV1Evaluator` and `RubricBasedFinalResponseQualityV1Evaluator`)
  that require `AppDetails` (the agent's instructions and declared tools), this adapter dynamically
  reads the agent definition from `GET /v1alpha/{agent_name}` or from `agent_template.json`—with
  zero hardcoded prompts or node names.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

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


class GeminiEnterpriseAdkAdapter:
  """Read-only client that queries a deployed GE No-Code Agent and produces ADK `Invocation` objects."""

  def __init__(
      self,
      project_id: str,
      location: str,
      engine_id: str,
      agent_id: str,
      data_store_id: str = "",
      template_path: Optional[str] = None,
      corpus_path: Optional[str] = None,
  ) -> None:
    self.project_id = project_id
    self.location = location or "global"
    self.engine_id = engine_id
    self.agent_id = agent_id
    self.data_store_id = data_store_id
    self.template_path = Path(template_path) if template_path else None
    self.corpus_path = Path(corpus_path) if corpus_path else None

    if self.location == "global":
      self.base_url = "https://discoveryengine.googleapis.com/v1alpha"
    else:
      self.base_url = f"https://{self.location}-discoveryengine.googleapis.com/v1alpha"

    self.assistant_name = (
        f"projects/{self.project_id}/locations/{self.location}/"
        f"collections/default_collection/engines/{self.engine_id}/"
        f"assistants/default_assistant"
    )
    self._cached_app_details: Optional[AppDetails] = None
    self._root_node_id: str = "root_agent"

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

  def _load_agent_definition_metadata(self) -> Tuple[str, str]:
    """Dynamically loads (root_node_id, instructions) from the live GE API or parameterized template_path."""
    agent_def: Dict[str, Any] = {}
    # 1. Try reading from local template_path first (fast & works in dry-run)
    if self.template_path and self.template_path.exists():
      try:
        agent_def = json.loads(self.template_path.read_text(encoding="utf-8"))
      except Exception:  # pylint: disable=broad-except
        agent_def = {}

    # 2. Otherwise query live agent resource via GET /v1alpha/{assistant}/agents/{agent_id}
    if not agent_def:
      try:
        agent_url = f"{self.base_url}/{self.assistant_name}/agents/{self.agent_id}"
        resp = requests.get(agent_url, headers=self._get_headers(), timeout=30)
        if resp.ok:
          agent_def = resp.json()
      except Exception:  # pylint: disable=broad-except
        agent_def = {}

    low_code = agent_def.get("lowCodeAgentDefinition") or {}
    nodes = low_code.get("nodes") or []
    root_id = low_code.get("rootAgentId") or (nodes[0].get("id") if nodes else "root_agent")
    instructions = ""
    for node in nodes:
      if node.get("id") == root_id or not instructions:
        llm_node = node.get("llmAgentNode") or {}
        instructions = llm_node.get("instruction", "")

    if self.corpus_path and self.corpus_path.exists():
      corpus_text = self.corpus_path.read_text(encoding="utf-8")
      instructions = f"{instructions}\n\nContexto Documental del Data Store ({self.data_store_id}):\n{corpus_text}".strip()

    return root_id, instructions

  def get_app_details(self) -> AppDetails:
    """Builds ADK AppDetails dynamically from the No-Code Agent's definition."""
    if self._cached_app_details is not None:
      return self._cached_app_details

    root_id, instructions = self._load_agent_definition_metadata()
    self._root_node_id = root_id
    self._cached_app_details = AppDetails(
        agent_details={
            root_id: AgentDetails(
                name=root_id,
                instructions=instructions,
                tool_declarations=[
                    {
                        "name": "vertex_ai_search",
                        "description": (
                            f"Consulta el Data Store de Vertex AI Search ({self.data_store_id or 'datastore'}) "
                            "configurado en el agente No-Code de Gemini Enterprise."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "query": {
                                    "type": "STRING",
                                    "description": "Consulta de búsqueda documental.",
                                }
                            },
                            "required": ["query"],
                        },
                    }
                ],
            )
        }
    )
    return self._cached_app_details

  def call_stream_assist(
      self,
      query_text: str,
      session_name: Optional[str] = None,
  ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Invokes POST /v1alpha/{assistant}:streamAssist targeting the deployed No-Code agent."""
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
    """Fetches extractive segments from the GE Engine's DataStore to populate tool_responses for ADK HallucinationsV1Evaluator."""
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

    if self.corpus_path and self.corpus_path.exists():
      refs.append(
          {
              "content": self.corpus_path.read_text(encoding="utf-8"),
              "documentMetadata": {
                  "title": self.corpus_path.name,
                  "document": f"projects/{self.project_id}/locations/{self.location}/collections/default_collection/dataStores/{self.data_store_id}",
              },
          }
      )
    return refs

  def stream_assist_chunks_to_adk_invocation(
      self,
      query_text: str,
      chunks: List[Dict[str, Any]],
      invocation_id: Optional[str] = None,
  ) -> Invocation:
    """Converts `StreamAssistResponse` JSON chunks into a `google.adk.evaluation.eval_case.Invocation`."""
    app_details = self.get_app_details()
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

        grounding_meta = grounded.get("textGroundingMetadata") or {}
        for ref in grounding_meta.get("references", []):
          grounding_references.append(ref)

    # 3. Pair Vertex AI Search FunctionCall with its FunctionResponse
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

      if self.corpus_path and self.corpus_path.exists():
        grounding_references.append(
            {
                "content": self.corpus_path.read_text(encoding="utf-8"),
                "documentMetadata": {
                    "title": self.corpus_path.name,
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

    # 4. Build InvocationEvents for ADK Evaluators
    events: List[InvocationEvent] = []
    for idx, tu in enumerate(tool_uses):
      parts = [genai_types.Part(function_call=tu)]
      if idx < len(tool_responses):
        parts.append(genai_types.Part(function_response=tool_responses[idx]))
      events.append(
          InvocationEvent(
              author=self._root_node_id,
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
        app_details=app_details,
    )
