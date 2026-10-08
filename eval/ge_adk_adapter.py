#!/usr/bin/env python3
"""Adapter that invokes a Gemini Enterprise No-Code / Low-Code Agent via :streamAssist
and translates its response into a native `google.adk.evaluation.eval_case.Invocation`.

This allows running all 7 official ADK Evaluation Criteria (https://adk.dev/evaluate/criteria/)
directly against Gemini Enterprise Agent Designer (No-Code / Low-Code) agents.
"""

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import google.auth
from google.auth.transport.requests import Request
from google.adk.evaluation.eval_case import IntermediateData, Invocation
from google.genai import types as genai_types
import requests


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
    for chunk in chunks:
      session_info = chunk.get("sessionInfo") or {}
      if session_info.get("session"):
        resolved_session = session_info["session"]

    return chunks, resolved_session

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
    intermediate_responses: List[Tuple[str, List[genai_types.Part]]] = []
    tool_uses: List[genai_types.FunctionCall] = []
    tool_responses: List[genai_types.FunctionResponse] = []
    grounding_references: List[Dict[str, Any]] = []
    seen_tool_calls: set[str] = set()

    for chunk in chunks:
      # 1. Top-level invocationTools list in StreamAssistResponse
      for tool_name in chunk.get("invocationTools", []):
        key = f"{tool_name}:{{}}"
        if key not in seen_tool_calls:
          seen_tool_calls.add(key)
          tool_uses.append(genai_types.FunctionCall(name=tool_name, args={}))

      answer = chunk.get("answer") or {}
      author = answer.get("adkAuthor") or "ge_no_code_agent"

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

        if text_piece:
          if is_thought:
            intermediate_responses.append(
                (author, [genai_types.Part.from_text(text=text_piece)])
            )
          else:
            final_text_parts.append(text_piece)

        # Extract grounding references from Vertex AI Search Data Stores
        grounding_meta = grounded.get("textGroundingMetadata") or {}
        for ref in grounding_meta.get("references", []):
          grounding_references.append(ref)

      # 3. Parse diagnosticInfo.plannerSteps if returned by GE
      diag = answer.get("diagnosticInfo") or {}
      for step in diag.get("plannerSteps", []):
        if "planStep" in step:
          ps = step["planStep"]
          for part in (ps.get("parts") or []):
            if "functionCall" in part:
              fc = part["functionCall"]
              fc_name = fc.get("name", "planner_tool")
              fc_args = fc.get("args") or {}
              key = f"{fc_name}:{json.dumps(fc_args, sort_keys=True)}"
              if key not in seen_tool_calls:
                seen_tool_calls.add(key)
                tool_uses.append(genai_types.FunctionCall(name=fc_name, args=fc_args))
        if "toolStep" in step:
          ts = step["toolStep"]
          for part in (ts.get("parts") or []):
            if "functionResult" in part:
              fr = part["functionResult"]
              tool_responses.append(
                  genai_types.FunctionResponse(
                      name=fr.get("name", "planner_tool"),
                      response=fr.get("result") or {},
                  )
              )

    # 4. If Vertex AI Search grounding references were retrieved, expose them as a
    #    `vertex_ai_search` tool call + response so `hallucinations_v1` and `tool_trajectory_avg_score`
    #    can inspect the retrieved passages for groundedness and tool trajectory verification.
    if grounding_references:
      ds_tool_name = "vertex_ai_search"
      if not any(tu.name == ds_tool_name for tu in tool_uses):
        tool_uses.append(
            genai_types.FunctionCall(
                name=ds_tool_name,
                args={"query": query_text},
            )
        )
      extracted_passages = []
      for idx, ref in enumerate(grounding_references, start=1):
        doc_meta = ref.get("documentMetadata") or {}
        extracted_passages.append(
            {
                "reference_index": idx,
                "title": doc_meta.get("title", ""),
                "uri": doc_meta.get("uri", ""),
                "document": doc_meta.get("document", ""),
                "content": ref.get("content", ""),
            }
        )
      tool_responses.append(
          genai_types.FunctionResponse(
              name=ds_tool_name,
              response={"references": extracted_passages},
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
        intermediate_data=IntermediateData(
            tool_uses=tool_uses,
            intermediate_responses=intermediate_responses,
            tool_responses=tool_responses,
        ),
    )
