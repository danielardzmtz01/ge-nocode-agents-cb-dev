#!/usr/bin/env python3
"""Automated Quality Gate Runner for Gemini Enterprise No-Code / Low-Code Agents
using Google's Agent Development Kit (`google-adk`) Evaluation Engine.

Executes a Golden Dataset (`EvalSet`) against a deployed GE No-Code agent in `dev`, `stg`, or `prd`,
converts the `:streamAssist` responses into ADK `Invocation` objects, and evaluates all configured
ADK criteria (`https://adk.dev/evaluate/criteria/`).
"""

import argparse
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.adk.evaluation.eval_case import EvalCase, Invocation
from google.adk.evaluation.eval_config import (
    get_eval_metrics_from_config,
    get_evaluation_criteria_or_default,
)
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus, PrebuiltMetrics
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.evaluator import Evaluator
from google.adk.evaluation.final_response_match_v2 import FinalResponseMatchV2Evaluator
from google.adk.evaluation.hallucinations_v1 import HallucinationsV1Evaluator
from google.adk.evaluation.rubric_based_final_response_quality_v1 import (
    RubricBasedFinalResponseQualityV1Evaluator,
)
from google.adk.evaluation.rubric_based_tool_use_quality_v1 import (
    RubricBasedToolUseV1Evaluator,
)
from google.adk.evaluation.trajectory_evaluator import TrajectoryEvaluator

# Add parent directory to sys.path so we can import cli and eval modules cleanly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cli.ge_agent_cli import load_env_vars  # noqa: E402
from eval.ge_adk_adapter import GeminiEnterpriseAdkAdapter  # noqa: E402


def resolve_adk_evaluator(eval_metric: EvalMetric) -> Evaluator:
  """Resolves the official ADK Evaluator for a given EvalMetric."""
  try:
    from google.adk.evaluation.metric_evaluator_registry import (
        DEFAULT_METRIC_EVALUATOR_REGISTRY,
    )
    return DEFAULT_METRIC_EVALUATOR_REGISTRY.get_evaluator(eval_metric)
  except ImportError:
    # Fallback if optional pandas/vertex_ai_eval_facade extras are not installed locally
    name = eval_metric.metric_name
    if name == PrebuiltMetrics.TOOL_TRAJECTORY_AVG_SCORE.value:
      return TrajectoryEvaluator(eval_metric=eval_metric)
    if name == PrebuiltMetrics.FINAL_RESPONSE_MATCH_V2.value:
      return FinalResponseMatchV2Evaluator(eval_metric=eval_metric)
    if name == PrebuiltMetrics.HALLUCINATIONS_V1.value:
      return HallucinationsV1Evaluator(eval_metric=eval_metric)
    if name == PrebuiltMetrics.RUBRIC_BASED_FINAL_RESPONSE_QUALITY_V1.value:
      return RubricBasedFinalResponseQualityV1Evaluator(eval_metric=eval_metric)
    if name == PrebuiltMetrics.RUBRIC_BASED_TOOL_USE_QUALITY_V1.value:
      return RubricBasedToolUseV1Evaluator(eval_metric=eval_metric)
    from google.adk.evaluation.response_evaluator import ResponseEvaluator
    return ResponseEvaluator(eval_metric=eval_metric)


async def maybe_await(value: Any) -> Any:
  if inspect.isawaitable(value):
    return await value
  return value


def extract_text_from_content(content: Any) -> str:
  if not content or not getattr(content, "parts", None):
    return ""
  return "".join(
      p.text for p in content.parts if getattr(p, "text", None)
  ).strip()


async def execute_eval_case_on_ge(
    adapter: GeminiEnterpriseAdkAdapter,
    eval_case: EvalCase,
    dry_run: bool = False,
) -> List[Invocation]:
  """Runs a single-turn or multi-turn EvalCase against the GE No-Code agent."""
  expected_invocations = eval_case.conversation or []
  if not expected_invocations:
    raise ValueError(
        f"EvalCase '{eval_case.eval_id}' does not contain a static `conversation` list."
    )

  if dry_run:
    simulated_invocations: List[Invocation] = []
    for exp in expected_invocations:
      query_text = extract_text_from_content(exp.user_content)
      expected_text = extract_text_from_content(exp.final_response)
      mock_replies: List[Dict[str, Any]] = []
      if exp.intermediate_data and exp.intermediate_data.tool_uses:
        for tu in exp.intermediate_data.tool_uses:
          mock_replies.append(
              {"functionCall": {"name": tu.name, "args": tu.args or {}}}
          )
      mock_replies.append(
          {
              "groundedContent": {
                  "content": {"role": "model", "text": expected_text},
                  "textGroundingMetadata": {
                      "references": [
                          {
                              "content": expected_text,
                              "documentMetadata": {
                                  "title": "Portal Oficial Gobierno de El Salvador",
                                  "uri": "gs://sv-gob-corpus/tramites.pdf",
                              },
                          }
                      ]
                  },
              }
          }
      )
      mock_chunks = [{"answer": {"replies": mock_replies}}]
      actual_inv = adapter.stream_assist_chunks_to_adk_invocation(
          query_text=query_text,
          chunks=mock_chunks,
          invocation_id=exp.invocation_id,
      )
      simulated_invocations.append(actual_inv)
    return simulated_invocations

  actual_invocations: List[Invocation] = []
  session_name: Optional[str] = None
  for exp in expected_invocations:
    query_text = extract_text_from_content(exp.user_content)
    chunks, session_name = adapter.call_stream_assist(
        query_text=query_text,
        session_name=session_name,
    )
    actual_inv = adapter.stream_assist_chunks_to_adk_invocation(
        query_text=query_text,
        chunks=chunks,
        invocation_id=exp.invocation_id,
    )
    actual_invocations.append(actual_inv)

  return actual_invocations


async def run_evaluation(args: argparse.Namespace) -> int:
  env_vars = load_env_vars(args.vars_file)
  env_name = env_vars.get("ENV", "dev")
  project_id = args.project_id or env_vars.get("GE_PROJECT_ID", "sv-gob-dev")
  location = args.location or env_vars.get("GE_LOCATION", "global")
  engine_id = args.engine_id or env_vars.get("GE_ENGINE_ID", "sv-engine-dev")
  agent_id = args.agent_id or env_vars.get("GE_AGENT_ID")

  if not agent_id and args.agent_id_file and Path(args.agent_id_file).exists():
    agent_id = Path(args.agent_id_file).read_text(encoding="utf-8").strip()
  agent_id = agent_id or "sv-citizen-assistant"

  # Configure Vertex AI environment variables for ADK LLM-as-a-Judge metrics
  os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
  os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
  os.environ.setdefault(
      "GOOGLE_CLOUD_LOCATION",
      "us-central1" if location == "global" else location,
  )

  eval_set_path = Path(args.eval_set_path)
  eval_config_path = Path(args.eval_config_path)

  eval_set = EvalSet.model_validate_json(eval_set_path.read_text(encoding="utf-8"))
  eval_config = get_evaluation_criteria_or_default(str(eval_config_path))
  eval_metrics = get_eval_metrics_from_config(eval_config)

  configured_metric_names = set(eval_config.criteria.keys())
  active_metrics = [
      m for m in eval_metrics if m.metric_name in configured_metric_names
  ]

  adapter = GeminiEnterpriseAdkAdapter(
      project_id=project_id,
      location=location,
      engine_id=engine_id,
      agent_id=agent_id,
  )

  print(
      f"[eval] Starting ADK Evaluation for Agent '{agent_id}' in {env_name.upper()} "
      f"(EvalSet: {eval_set.eval_set_id}, Cases: {len(eval_set.eval_cases)})"
  )

  case_reports: List[Dict[str, Any]] = []
  overall_passed = True

  for eval_case in eval_set.eval_cases:
    print(f"  -> Running case: {eval_case.eval_id} ...")
    actual_invocations = await execute_eval_case_on_ge(
        adapter=adapter,
        eval_case=eval_case,
        dry_run=args.dry_run,
    )

    metric_results_summary: List[Dict[str, Any]] = []
    case_passed = True

    for eval_metric in active_metrics:
      # In --dry-run, run TrajectoryEvaluator natively and mock LLM/optional judge calls
      if args.dry_run and eval_metric.metric_name != PrebuiltMetrics.TOOL_TRAJECTORY_AVG_SCORE.value:
        score = 1.0
        status_str = "PASSED (DRY_RUN)"
        passed = True
      else:
        evaluator = resolve_adk_evaluator(eval_metric)
        eval_result = await maybe_await(
            evaluator.evaluate_invocations(
                actual_invocations=actual_invocations,
                expected_invocations=eval_case.conversation,
                conversation_scenario=eval_case.conversation_scenario,
            )
        )
        score = (
            round(float(eval_result.overall_score), 4)
            if eval_result.overall_score is not None
            else 0.0
        )
        passed = eval_result.overall_eval_status == EvalStatus.PASSED
        status_str = "PASSED" if passed else "FAILED"

      if not passed:
        case_passed = False
        overall_passed = False

      metric_results_summary.append(
          {
              "metric_name": eval_metric.metric_name,
              "score": score,
              "threshold": eval_metric.threshold,
              "status": status_str,
          }
      )

    case_reports.append(
        {
            "eval_id": eval_case.eval_id,
            "passed": case_passed,
            "metrics": metric_results_summary,
        }
    )

  report_data = {
      "environment": env_name,
      "project_id": project_id,
      "engine_id": engine_id,
      "agent_id": agent_id,
      "eval_set_id": eval_set.eval_set_id,
      "overall_passed": overall_passed,
      "cases": case_reports,
  }

  output_dir = Path(args.output_dir)
  output_dir.mkdir(parents=True, exist_ok=True)
  json_report_path = output_dir / f"eval_report_{env_name}.json"
  md_report_path = output_dir / f"eval_report_{env_name}.md"

  json_report_path.write_text(
      json.dumps(report_data, indent=2, ensure_ascii=False) + "\n",
      encoding="utf-8",
  )

  md_lines = [
      f"## Reporte de Evaluación ADK - Agente No-Code (`{env_name.upper()}`)",
      "",
      f"- **Agente ID**: `{agent_id}`",
      f"- **Engine ID**: `{engine_id}` (`{project_id}`)",
      f"- **Golden Dataset**: `{eval_set.eval_set_id}`",
      f"- **Resultado Global**: {'PASSED' if overall_passed else 'FAILED'}",
      "",
      "| Caso (`eval_id`) | Métrica ADK | Score | Threshold | Estado |",
      "| :--- | :--- | :---: | :---: | :---: |",
  ]
  for c in case_reports:
    for m in c["metrics"]:
      md_lines.append(
          f"| `{c['eval_id']}` | `{m['metric_name']}` | `{m['score']}` | `{m['threshold']}` | **{m['status']}** |"
      )

  md_content = "\n".join(md_lines) + "\n"
  md_report_path.write_text(md_content, encoding="utf-8")
  print("\n" + md_content)

  gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
  if gh_summary:
    with open(gh_summary, "a", encoding="utf-8") as f:
      f.write(md_content)

  if not overall_passed:
    print(
        f"[eval] Quality Gate FAILED for agent '{agent_id}' in {env_name.upper()}. Blocking promotion.",
        file=sys.stderr,
    )
    return 1

  print(f"[eval] Quality Gate PASSED for agent '{agent_id}' in {env_name.upper()}.")
  return 0


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Run google-adk evaluation criteria against a Gemini Enterprise No-Code Agent"
  )
  parser.add_argument("--vars-file", default="spec_variables.auto.yaml")
  parser.add_argument("--project-id", help="Override GCP Project ID")
  parser.add_argument("--location", help="Override Discovery Engine Location")
  parser.add_argument("--engine-id", help="Override Gemini Enterprise Engine ID")
  parser.add_argument("--agent-id", help="Override Agent ID")
  parser.add_argument("--agent-id-file", help="Path to file containing Agent ID")
  parser.add_argument(
      "--eval-set-path",
      default="agents/sv_citizen_assistant/golden_dataset.evalset.json",
  )
  parser.add_argument(
      "--eval-config-path",
      default="agents/sv_citizen_assistant/eval_config.json",
  )
  parser.add_argument("--output-dir", default="eval_results")
  parser.add_argument(
      "--dry-run",
      action="store_true",
      help="Validate EvalSet, EvalConfig, and ADK TrajectoryEvaluator without calling live endpoints",
  )
  args = parser.parse_args()
  sys.exit(asyncio.run(run_evaluation(args)))


if __name__ == "__main__":
  main()
