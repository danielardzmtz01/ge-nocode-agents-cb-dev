#!/usr/bin/env python3
"""CLI for managing Gemini Enterprise (Discovery Engine) No-Code / Low-Code Agents across environments (dev -> stg -> prd).

Supports:
- pull: Export an agent definition from GE Agent Designer UI and parameterize environment variables.
- push: Hydrate agent_template.json in-place with environment variables, Create/Update the agent, and trigger :deployLowCode.
- request-review: Trigger :requestAgentReview for HITL validation in STG.
- publish: Create an immutable AgentRevision (/revisions) and call :publish in PRD.
- rollback: Revert an agent to a previous revision via :rollback.
"""

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import google.auth
from google.auth.transport.requests import Request
import requests
import yaml


READ_ONLY_AGENT_FIELDS = {
    "name",
    "state",
    "createTime",
    "updateTime",
    "failureReason",
    "Locale",
}


def get_api_base_url(location: str) -> str:
  """Returns the regional or global Discovery Engine v1alpha endpoint."""
  if location == "global" or not location:
    return "https://discoveryengine.googleapis.com/v1alpha"
  return f"https://{location}-discoveryengine.googleapis.com/v1alpha"


def get_assistant_parent(project_id: str, location: str, engine_id: str) -> str:
  """Builds the parent resource path for the default assistant in a GE engine."""
  return (
      f"projects/{project_id}/locations/{location}/collections/default_collection/"
      f"engines/{engine_id}/assistants/default_assistant"
  )


def get_auth_headers(quota_project: Optional[str] = None) -> Dict[str, str]:
  """Obtains OAuth2 Bearer headers using Application Default Credentials (ADC)."""
  credentials, default_project = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  credentials.refresh(Request())
  headers = {
      "Authorization": f"Bearer {credentials.token}",
      "Content-Type": "application/json",
  }
  project_for_quota = quota_project or default_project
  if project_for_quota:
    headers["X-Goog-User-Project"] = project_for_quota
  return headers


def load_env_vars(vars_file: Optional[str] = None) -> Dict[str, str]:
  """Loads environment variables from spec_variables.auto.yaml (if present) and OS env."""
  merged: Dict[str, str] = {}
  default_auto = Path("spec_variables.auto.yaml")
  target_file = Path(vars_file) if vars_file else (default_auto if default_auto.exists() else None)

  if target_file and target_file.exists():
    with open(target_file, "r", encoding="utf-8") as f:
      data = yaml.safe_load(f) or {}
      for k, v in data.items():
        if v is not None:
          merged[str(k).upper()] = str(v)

  # Allow OS environment variables to override or supplement
  for key in (
      "ENV",
      "GE_PROJECT_ID",
      "GE_LOCATION",
      "GE_ENGINE_ID",
      "GE_DATA_STORE_ID",
      "GE_AGENT_ID",
      "GE_SHARING_SCOPE",
      "GE_MODEL",
  ):
    if key in os.environ and os.environ[key]:
      merged[key] = os.environ[key]

  # Default sharing scope by environment if not explicitly provided
  env_lower = merged.get("ENV", "dev").lower()
  if "GE_SHARING_SCOPE" not in merged:
    if env_lower == "dev":
      merged["GE_SHARING_SCOPE"] = "PRIVATE"
    elif env_lower == "stg":
      merged["GE_SHARING_SCOPE"] = "RESTRICTED"
    elif env_lower == "prd":
      merged["GE_SHARING_SCOPE"] = "ALL_USERS"

  return merged


def hydrate_template(template_str: str, env_vars: Dict[str, str]) -> Dict[str, Any]:
  """Replaces ${VAR_NAME} placeholders in agent_template.json with environment values."""
  def replacer(match: re.Match[str]) -> str:
    var_name = match.group(1)
    if var_name not in env_vars:
      raise ValueError(
          f"Missing required environment variable '${{{var_name}}}' when hydrating agent_template.json. "
          f"Available variables: {sorted(env_vars.keys())}"
      )
    return env_vars[var_name]

  hydrated_str = re.sub(r"\$\{([A-Z0-9_]+)\}", replacer, template_str)
  return json.loads(hydrated_str)


def parameterize_agent_payload(
    raw_agent: Dict[str, Any],
    project_id: str,
    location: str,
    engine_id: str,
    data_store_id: Optional[str] = None,
    env_name: str = "dev",
) -> Dict[str, Any]:
  """Strips server-generated fields and replaces env-specific IDs with ${...} placeholders."""
  cleaned = copy.deepcopy(raw_agent)
  for ro_field in READ_ONLY_AGENT_FIELDS:
    cleaned.pop(ro_field, None)

  # Remove runtime-only deployed_nodes inside lowCodeAgentDefinition if present
  if "lowCodeAgentDefinition" in cleaned:
    cleaned["lowCodeAgentDefinition"].pop("deployedNodes", None)

  serialized = json.dumps(cleaned, indent=2, ensure_ascii=False)
  serialized = serialized.replace(f"projects/{project_id}", "projects/${GE_PROJECT_ID}")
  serialized = serialized.replace(f"locations/{location}", "locations/${GE_LOCATION}")
  serialized = serialized.replace(f"engines/{engine_id}", "engines/${GE_ENGINE_ID}")
  if data_store_id:
    serialized = serialized.replace(f"dataStores/{data_store_id}", "dataStores/${GE_DATA_STORE_ID}")
    serialized = serialized.replace(data_store_id, "${GE_DATA_STORE_ID}")

  # Replace sharing scope with ${GE_SHARING_SCOPE}
  parsed = json.loads(serialized)
  if "sharingConfig" in parsed and "scope" in parsed["sharingConfig"]:
    parsed["sharingConfig"]["scope"] = "${GE_SHARING_SCOPE}"

  return parsed


def resolve_project_number(
    base_url: str,
    assistant_parent: str,
    project_id: str,
    headers: Dict[str, str],
) -> str:
  """Resolves the numeric GCP project_number from Discovery Engine resource names."""
  if project_id.isdigit():
    return project_id
  resp = requests.get(f"{base_url}/{assistant_parent}", headers=headers, timeout=30)
  if resp.status_code == 200:
    name = resp.json().get("name", "")
    parts = name.split("/")
    if len(parts) >= 2 and parts[0] == "projects" and parts[1].isdigit():
      return parts[1]
  return project_id


def normalize_low_code_payload(
    hydrated_agent: Dict[str, Any],
    project_id: str,
    project_number: str,
) -> Dict[str, Any]:
  """Normalizes LowCodeAgentDefinition dataStoreSpecs to use numeric project_number and strips fields managed by lifecycle RPCs."""
  payload = copy.deepcopy(hydrated_agent)
  # sharingConfig is managed via :requestAgentReview / PATCH ?updateMask=sharingConfig
  payload.pop("sharingConfig", None)

  if "lowCodeAgentDefinition" in payload:
    # starterPrompts is output-only when draftStarterPrompts is used; :deployLowCode promotes draftStarterPrompts -> starterPrompts
    if "draftStarterPrompts" in payload["lowCodeAgentDefinition"]:
      payload.pop("starterPrompts", None)
    for node in payload["lowCodeAgentDefinition"].get("nodes", []):
      llm_node = node.get("llmAgentNode", {})
      specs = llm_node.get("dataStoreSpecs", {}).get("specs", [])
      for spec in specs:
        ds = spec.get("dataStore", "")
        if ds.startswith(f"projects/{project_id}/"):
          spec["dataStore"] = ds.replace(
              f"projects/{project_id}/", f"projects/{project_number}/", 1
          )
  return payload


def find_existing_agent(
    base_url: str,
    assistant_parent: str,
    headers: Dict[str, str],
    agent_id: Optional[str],
    display_name: Optional[str],
) -> Optional[Dict[str, Any]]:
  """Finds an existing agent in the target GE engine by ID or displayName."""
  if agent_id:
    url = f"{base_url}/{assistant_parent}/agents/{agent_id}"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 200:
      return resp.json()
    if resp.status_code != 404:
      resp.raise_for_status()

  # Fallback: search in ListAgents by displayName
  if display_name:
    list_url = f"{base_url}/{assistant_parent}/agents"
    resp = requests.get(list_url, headers=headers, timeout=30)
    resp.raise_for_status()
    for agent in resp.json().get("agents", []):
      if agent.get("displayName") == display_name:
        return agent
  return None


def cmd_pull(args: argparse.Namespace) -> None:
  """Exports a No-Code/Low-Code agent from GE and writes a parameterized agent_template.json."""
  env_vars = load_env_vars(args.vars_file)
  project_id = args.project_id or env_vars.get("GE_PROJECT_ID")
  location = args.location or env_vars.get("GE_LOCATION", "global")
  engine_id = args.engine_id or env_vars.get("GE_ENGINE_ID")
  agent_id = args.agent_id or env_vars.get("GE_AGENT_ID")
  data_store_id = args.data_store_id or env_vars.get("GE_DATA_STORE_ID")

  if not all([project_id, engine_id, agent_id]):
    raise ValueError("pull requires --project-id, --engine-id, and --agent-id (or via spec_variables.auto.yaml).")

  base_url = get_api_base_url(location)
  assistant_parent = get_assistant_parent(project_id, location, engine_id)
  url = f"{base_url}/{assistant_parent}/agents/{agent_id}"

  print(f"[pull] Fetching agent definition from: {url}")
  headers = get_auth_headers(project_id)
  resp = requests.get(url, headers=headers, timeout=30)
  resp.raise_for_status()
  raw_agent = resp.json()

  parameterized = parameterize_agent_payload(
      raw_agent=raw_agent,
      project_id=project_id,
      location=location,
      engine_id=engine_id,
      data_store_id=data_store_id,
      env_name=env_vars.get("ENV", "dev"),
  )

  out_path = Path(args.template_path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with open(out_path, "w", encoding="utf-8") as f:
    json.dump(parameterized, f, indent=2, ensure_ascii=False)
    f.write("\n")

  print(f"[pull] Saved parameterized No-Code agent template to: {out_path}")


def cmd_push(args: argparse.Namespace) -> None:
  """Hydrates agent_template.json and creates/updates + deploys the No-Code agent in the target environment."""
  env_vars = load_env_vars(args.vars_file)
  template_path = Path(args.template_path)
  if not template_path.exists():
    raise FileNotFoundError(f"Agent template file not found: {template_path}")

  raw_template = template_path.read_text(encoding="utf-8")
  hydrated_agent = hydrate_template(raw_template, env_vars)

  project_id = env_vars["GE_PROJECT_ID"]
  location = env_vars.get("GE_LOCATION", "global")
  engine_id = env_vars["GE_ENGINE_ID"]
  agent_id = args.agent_id or env_vars.get("GE_AGENT_ID")
  env_name = env_vars.get("ENV", "dev")

  base_url = get_api_base_url(location)
  assistant_parent = get_assistant_parent(project_id, location, engine_id)

  print(f"[push] Environment: {env_name.upper()} | Engine: {engine_id} | Project: {project_id}")
  if args.dry_run:
    print("[push] --dry-run enabled. Hydrated agent payload:")
    print(json.dumps(hydrated_agent, indent=2, ensure_ascii=False))
    return

  headers = get_auth_headers(project_id)
  project_number = resolve_project_number(base_url, assistant_parent, project_id, headers)
  api_payload = normalize_low_code_payload(hydrated_agent, project_id, project_number)

  existing = find_existing_agent(
      base_url=base_url,
      assistant_parent=assistant_parent,
      headers=headers,
      agent_id=agent_id,
      display_name=hydrated_agent.get("displayName"),
  )

  if existing:
    agent_resource_name = existing["name"]
    if "lowCodeAgentDefinition" in api_payload:
      update_mask = "displayName,description,lowCodeAgentDefinition"
    else:
      update_mask = "displayName,description,starterPrompts,noCodeAgentDefinition"
    patch_url = f"{base_url}/{agent_resource_name}?updateMask={update_mask}"
    api_payload["name"] = agent_resource_name
    print(f"[push] Updating existing agent: {agent_resource_name}")
    resp = requests.patch(patch_url, headers=headers, json=api_payload, timeout=60)
    if not resp.ok:
      raise RuntimeError(f"UpdateAgent failed ({resp.status_code}): {resp.text}")
    saved_agent = resp.json()
  else:
    create_url = f"{base_url}/{assistant_parent}/agents"
    print(f"[push] Creating new agent in: {assistant_parent}/agents")
    resp = requests.post(create_url, headers=headers, json=api_payload, timeout=60)
    if not resp.ok:
      raise RuntimeError(f"CreateAgent failed ({resp.status_code}): {resp.text}")
    saved_agent = resp.json()
    agent_resource_name = saved_agent["name"]

  resolved_agent_id = agent_resource_name.split("/")[-1]
  print(f"[push] Agent resource saved: {agent_resource_name} (ID: {resolved_agent_id})")

  # Trigger :deployLowCode if lowCodeAgentDefinition is present, else :deploy
  if "lowCodeAgentDefinition" in api_payload:
    deploy_url = f"{base_url}/{agent_resource_name}:deployLowCode"
    deploy_body = {"name": agent_resource_name, "deployMode": "DEPLOY"}
    print(f"[push] Compiling & deploying Low-Code/No-Code nodes via: {deploy_url}")
  else:
    deploy_url = f"{base_url}/{agent_resource_name}:deploy"
    deploy_body = {"name": agent_resource_name}
    print(f"[push] Deploying agent via: {deploy_url}")

  deploy_resp = requests.post(deploy_url, headers=headers, json=deploy_body, timeout=120)
  if not deploy_resp.ok:
    raise RuntimeError(f"Deploy failed ({deploy_resp.status_code}): {deploy_resp.text}")

  if saved_agent.get("state", "PRIVATE") == "PRIVATE":
    rev_url = f"{base_url}/{agent_resource_name}:requestAgentReview"
    requests.post(rev_url, headers=headers, json={"name": agent_resource_name}, timeout=30)

  print(f"[push] Successfully deployed agent '{hydrated_agent.get('displayName')}' (ID: {resolved_agent_id})")

  if args.output_agent_id_file:
    Path(args.output_agent_id_file).write_text(resolved_agent_id, encoding="utf-8")


def cmd_request_review(args: argparse.Namespace) -> None:
  """Requests formal review (:requestAgentReview) in STG for HITL approval."""
  env_vars = load_env_vars(args.vars_file)
  project_id = env_vars["GE_PROJECT_ID"]
  location = env_vars.get("GE_LOCATION", "global")
  engine_id = env_vars["GE_ENGINE_ID"]
  agent_id = args.agent_id or env_vars["GE_AGENT_ID"]
  sharing_scope = env_vars.get("GE_SHARING_SCOPE", "RESTRICTED")

  base_url = get_api_base_url(location)
  agent_name = f"{get_assistant_parent(project_id, location, engine_id)}/agents/{agent_id}"
  url = f"{base_url}/{agent_name}:requestAgentReview"

  if args.dry_run:
    print(f"[request-review] --dry-run: POST {url}")
    return

  headers = get_auth_headers(project_id)
  get_resp = requests.get(f"{base_url}/{agent_name}", headers=headers, timeout=30)
  get_resp.raise_for_status()
  current_state = get_resp.json().get("state", "PRIVATE")

  if current_state == "PRIVATE":
    resp = requests.post(url, headers=headers, json={"name": agent_name}, timeout=30)
    if not resp.ok:
      raise RuntimeError(f"RequestAgentReview failed ({resp.status_code}): {resp.text}")
    new_state = resp.json().get("state")
    print(f"[request-review] Agent review requested for: {agent_name} (state: {current_state} -> {new_state})")
  else:
    print(f"[request-review] Agent {agent_name} is already in state '{current_state}' (out of PRIVATE).")

  if sharing_scope and sharing_scope != "PRIVATE":
    patch_url = f"{base_url}/{agent_name}?updateMask=sharingConfig"
    patch_body = {"name": agent_name, "sharingConfig": {"scope": sharing_scope}}
    patch_resp = requests.patch(patch_url, headers=headers, json=patch_body, timeout=30)
    if patch_resp.ok:
      print(f"[request-review] Updated sharingConfig.scope -> {sharing_scope}")


def cmd_publish(args: argparse.Namespace) -> None:
  """Enables, updates sharing scope, and creates/links an immutable AgentRevision (:publish) in PRD."""
  env_vars = load_env_vars(args.vars_file)
  project_id = env_vars["GE_PROJECT_ID"]
  location = env_vars.get("GE_LOCATION", "global")
  engine_id = env_vars["GE_ENGINE_ID"]
  agent_id = args.agent_id or env_vars["GE_AGENT_ID"]
  sharing_scope = env_vars.get("GE_SHARING_SCOPE", "ALL_USERS")

  base_url = get_api_base_url(location)
  agent_name = f"{get_assistant_parent(project_id, location, engine_id)}/agents/{agent_id}"
  publish_url = f"{base_url}/{agent_name}:publish"
  label = args.version_description or f"CI/CD automated release ({env_vars.get('ENV', 'prd')})"

  if args.dry_run:
    print(f"[publish] --dry-run: POST {publish_url} with label='{label}' and sharingConfig.scope='{sharing_scope}'")
    return

  headers = get_auth_headers(project_id)
  get_resp = requests.get(f"{base_url}/{agent_name}", headers=headers, timeout=30)
  get_resp.raise_for_status()
  current_state = get_resp.json().get("state", "PRIVATE")

  if current_state == "PRIVATE":
    rev_url = f"{base_url}/{agent_name}:requestAgentReview"
    rev_resp = requests.post(rev_url, headers=headers, json={"name": agent_name}, timeout=30)
    if not rev_resp.ok:
      raise RuntimeError(f"RequestAgentReview failed ({rev_resp.status_code}): {rev_resp.text}")
    current_state = rev_resp.json().get("state", current_state)
    print(f"[publish] Transitioned agent out of PRIVATE -> {current_state}")

  if current_state in ("DISABLED", "SUSPENDED"):
    enable_url = f"{base_url}/{agent_name}:enableAgent"
    en_resp = requests.post(enable_url, headers=headers, json={"name": agent_name}, timeout=30)
    if not en_resp.ok:
      raise RuntimeError(f"EnableAgent failed ({en_resp.status_code}): {en_resp.text}")
    current_state = en_resp.json().get("state", "ENABLED")
    print(f"[publish] Enabled agent -> {current_state}")

  if sharing_scope:
    patch_url = f"{base_url}/{agent_name}?updateMask=sharingConfig"
    patch_body = {"name": agent_name, "sharingConfig": {"scope": sharing_scope}}
    patch_resp = requests.patch(patch_url, headers=headers, json=patch_body, timeout=30)
    if not patch_resp.ok:
      raise RuntimeError(f"Updating sharingConfig failed ({patch_resp.status_code}): {patch_resp.text}")
    print(f"[publish] Updated sharingConfig.scope -> {sharing_scope}")

  print(f"[publish] Publishing agent snapshot (label='{label}') at: {publish_url}")
  pub_body: Dict[str, Any] = {"name": agent_name, "label": label}
  pub_resp = requests.post(publish_url, headers=headers, json=pub_body, timeout=60)
  if not pub_resp.ok:
    raise RuntimeError(f"PublishAgent failed ({pub_resp.status_code}): {pub_resp.text}")
  published_agent = pub_resp.json().get("agent", {})
  active_rev = published_agent.get("activeRevision", "")
  print(f"[publish] Successfully published agent {agent_name} (activeRevision={active_rev})")


def cmd_rollback(args: argparse.Namespace) -> None:
  """Rolls back an agent in PRD to a previous immutable revision (:rollback)."""
  env_vars = load_env_vars(args.vars_file)
  project_id = env_vars["GE_PROJECT_ID"]
  location = env_vars.get("GE_LOCATION", "global")
  engine_id = env_vars["GE_ENGINE_ID"]
  agent_id = args.agent_id or env_vars["GE_AGENT_ID"]

  base_url = get_api_base_url(location)
  agent_name = f"{get_assistant_parent(project_id, location, engine_id)}/agents/{agent_id}"
  rollback_url = f"{base_url}/{agent_name}:rollback"
  body: Dict[str, Any] = {"name": agent_name}
  if args.revision_id:
    body["revisionId"] = args.revision_id

  if args.dry_run:
    print(f"[rollback] --dry-run: POST {rollback_url} with {json.dumps(body)}")
    return

  headers = get_auth_headers(project_id)
  resp = requests.post(rollback_url, headers=headers, json=body, timeout=60)
  resp.raise_for_status()
  print(f"[rollback] Rolled back agent {agent_name} cleanly.")


def cmd_delete(args: argparse.Namespace) -> None:
  """Deletes a custom No-Code agent from the target Gemini Enterprise Engine (used to reset STG/PRD for clean testing)."""
  env_vars = load_env_vars(args.vars_file)
  project_id = env_vars["GE_PROJECT_ID"]
  location = env_vars.get("GE_LOCATION", "global")
  engine_id = env_vars["GE_ENGINE_ID"]
  agent_id = args.agent_id or env_vars.get("GE_AGENT_ID")
  display_name = args.display_name

  if not display_name and Path(args.template_path).exists():
    raw_template = Path(args.template_path).read_text(encoding="utf-8")
    display_name = hydrate_template(raw_template, env_vars).get("displayName")

  base_url = get_api_base_url(location)
  assistant_parent = get_assistant_parent(project_id, location, engine_id)
  headers = get_auth_headers(project_id)

  existing = find_existing_agent(
      base_url=base_url,
      assistant_parent=assistant_parent,
      headers=headers,
      agent_id=agent_id,
      display_name=display_name,
  )
  if not existing:
    print(f"[delete] No matching custom agent found in {project_id} ({engine_id}). Environment is already clean.")
    return

  agent_resource_name = existing["name"]
  del_url = f"{base_url}/{agent_resource_name}"
  if args.dry_run:
    print(f"[delete] --dry-run: DELETE {del_url}")
    return

  # If the agent is currently ENABLED, disable/suspend before deleting if needed
  state = existing.get("state", "PRIVATE")
  if state == "ENABLED":
    disable_url = f"{base_url}/{agent_resource_name}:disableAgent"
    requests.post(disable_url, headers=headers, json={"name": agent_resource_name}, timeout=30)

  resp = requests.delete(del_url, headers=headers, timeout=60)
  if resp.status_code in (200, 204, 404):
    print(f"[delete] Successfully deleted custom agent: {agent_resource_name}")
  else:
    raise RuntimeError(f"DeleteAgent failed ({resp.status_code}): {resp.text}")


def build_parser() -> argparse.ArgumentParser:
  parent_parser = argparse.ArgumentParser(add_help=False)
  parent_parser.add_argument(
      "--vars-file",
      default="spec_variables.auto.yaml",
      help="Path to in-place generated environment variables YAML file (default: spec_variables.auto.yaml)",
  )

  parser = argparse.ArgumentParser(
      description="Gemini Enterprise No-Code / Low-Code Agent GitOps CLI (dev -> stg -> prd)",
      parents=[parent_parser],
  )

  subparsers = parser.add_subparsers(dest="command", required=True)

  # pull
  p_pull = subparsers.add_parser("pull", parents=[parent_parser], help="Export agent from GE and parameterize into agent_template.json")
  p_pull.add_argument("--project-id", help="GCP Project ID")
  p_pull.add_argument("--location", default="global", help="Discovery Engine location (global, us, eu)")
  p_pull.add_argument("--engine-id", help="Gemini Enterprise Engine ID")
  p_pull.add_argument("--agent-id", help="Agent ID in Gemini Enterprise")
  p_pull.add_argument("--data-store-id", help="Data Store ID to parameterize as ${GE_DATA_STORE_ID}")
  p_pull.add_argument(
      "--template-path",
      default="agents/sv_citizen_assistant/agent_template.json",
      help="Output path for parameterized agent_template.json",
  )
  p_pull.set_defaults(func=cmd_pull)

  # push
  p_push = subparsers.add_parser("push", parents=[parent_parser], help="Hydrate agent_template.json and deploy to target GE environment")
  p_push.add_argument(
      "--template-path",
      default="agents/sv_citizen_assistant/agent_template.json",
      help="Path to agent_template.json",
  )
  p_push.add_argument("--agent-id", help="Optional explicit Agent ID to update")
  p_push.add_argument("--output-agent-id-file", help="Write resolved Agent ID to a file for downstream steps")
  p_push.add_argument("--dry-run", action="store_true", help="Validate and print hydrated payload without API calls")
  p_push.set_defaults(func=cmd_push)

  # request-review
  p_rev = subparsers.add_parser("request-review", parents=[parent_parser], help="Trigger :requestAgentReview for HITL validation in STG")
  p_rev.add_argument("--agent-id", help="Agent ID")
  p_rev.add_argument("--dry-run", action="store_true")
  p_rev.set_defaults(func=cmd_request_review)

  # publish
  p_pub = subparsers.add_parser("publish", parents=[parent_parser], help="Create immutable revision and :publish agent in PRD")
  p_pub.add_argument("--agent-id", help="Agent ID")
  p_pub.add_argument("--version-description", help="Description for the immutable AgentRevision")
  p_pub.add_argument("--dry-run", action="store_true")
  p_pub.set_defaults(func=cmd_publish)

  # rollback
  p_rb = subparsers.add_parser("rollback", parents=[parent_parser], help="Rollback agent in PRD to a previous revision (:rollback)")
  p_rb.add_argument("--agent-id", help="Agent ID")
  p_rb.add_argument("--revision-id", help="Target revision ID to roll back to")
  p_rb.add_argument("--dry-run", action="store_true")
  p_rb.set_defaults(func=cmd_rollback)

  # delete
  p_del = subparsers.add_parser("delete", parents=[parent_parser], help="Delete custom No-Code agent from target GE environment (reset for demo)")
  p_del.add_argument("--agent-id", help="Optional explicit Agent ID to delete")
  p_del.add_argument("--display-name", help="Optional display name to match")
  p_del.add_argument(
      "--template-path",
      default="agents/sv_citizen_assistant/agent_template.json",
      help="Path to agent_template.json to resolve displayName",
  )
  p_del.add_argument("--dry-run", action="store_true")
  p_del.set_defaults(func=cmd_delete)

  return parser


def main() -> None:
  parser = build_parser()
  args = parser.parse_args()
  try:
    args.func(args)
  except Exception as exc:  # pylint: disable=broad-except
    print(f"[ERROR] {exc}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
