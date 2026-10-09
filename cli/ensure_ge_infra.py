#!/usr/bin/env python3
"""Idempotent helper invoked by Terraform (`terraform_data.gemini_enterprise_engine_and_corpus`)
to provision, reconcile, or destroy (`--destroy`) Gemini Enterprise v1alpha resources that do not
yet have native Terraform provider resources:
1. LicenseConfig & UserStore (`v1alpha` - `SUBSCRIPTION_TIER_SEARCH_AND_ASSISTANT`)
2. Official GOES Corpus Document (`manual-oficial-tramites-goes-2026`) inside the Terraform-managed DataStore
3. Gemini Enterprise Engine (`sv-citizen-engine` with `APP_TYPE_INTRANET` & `SEARCH_ADD_ON_LLM`)
4. Default Assistant (`default_assistant`)
"""

import argparse
import base64
import json
from pathlib import Path
import sys
import time
import google.auth
from google.auth.transport.requests import Request
import requests


def get_headers(project_id: str) -> dict[str, str]:
  creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  creds.refresh(Request())
  return {
      "Authorization": f"Bearer {creds.token}",
      "Content-Type": "application/json",
      "X-Goog-User-Project": project_id,
  }


def wait_lro(base_url: str, op: dict, project_id: str, timeout_sec: int = 180) -> dict:
  if op.get("done"):
    if "error" in op:
      raise RuntimeError(f"LRO failed: {json.dumps(op['error'])}")
    return op
  op_name = op["name"]
  url = f"{base_url}/{op_name}"
  deadline = time.time() + timeout_sec
  while time.time() < deadline:
    resp = requests.get(url, headers=get_headers(project_id), timeout=30)
    if resp.status_code == 404:
      return op
    resp.raise_for_status()
    data = resp.json()
    if data.get("done"):
      if "error" in data:
        raise RuntimeError(f"LRO failed: {json.dumps(data['error'])}")
      return data
    time.sleep(3)
  raise TimeoutError(f"LRO timed out: {op_name}")


def ensure_ge_infrastructure(
    project_id: str,
    location: str,
    engine_id: str,
    data_store_id: str,
    corpus_file: str,
) -> None:
  headers = get_headers(project_id)
  base_url = (
      "https://discoveryengine.googleapis.com/v1alpha"
      if location == "global"
      else f"https://{location}-discoveryengine.googleapis.com/v1alpha"
  )
  parent = f"projects/{project_id}/locations/{location}/collections/default_collection"

  # 1. Ensure LicenseConfig & UserStore (auto-register licenses)
  r_lc = requests.get(
      f"{base_url}/projects/{project_id}/locations/{location}/licenseConfigs",
      headers=headers,
      timeout=30,
  )
  if r_lc.status_code == 200:
    lcs = r_lc.json().get("licenseConfigs", [])
    if lcs:
      lc_name = lcs[0]["name"]
      print(f"[terraform-ge-workaround] LicenseConfig already exists: {lc_name}")
    else:
      lc_url = f"{base_url}/projects/{project_id}/locations/{location}/licenseConfigs?licenseConfigId=goes-ge-trial"
      lc_body = {
          "licenseCount": 50,
          "subscriptionTier": "SUBSCRIPTION_TIER_SEARCH_AND_ASSISTANT",
          "subscriptionTerm": "SUBSCRIPTION_TERM_ONE_MONTH",
          "freeTrial": True,
      }
      r_create_lc = requests.post(lc_url, headers=headers, json=lc_body, timeout=60)
      if r_create_lc.status_code in (200, 201):
        lc_name = r_create_lc.json()["name"]
        print(f"[terraform-ge-workaround] Created LicenseConfig: {lc_name}")
      else:
        lc_name = ""
    if lc_name:
      us_url = f"{base_url}/projects/{project_id}/locations/{location}/userStores/default_user_store"
      requests.patch(
          us_url,
          headers=headers,
          json={"defaultLicenseConfig": lc_name, "enableLicenseAutoRegister": True},
          timeout=60,
      )

  # 2. Ensure Official GOES Corpus Document in Terraform-managed DataStore
  corpus_path = Path(corpus_file)
  if corpus_path.exists():
    corpus_text = corpus_path.read_text(encoding="utf-8")
    doc_id = "manual-oficial-tramites-goes-2026"
    doc_url = f"{base_url}/{parent}/dataStores/{data_store_id}/branches/default_branch/documents/{doc_id}"
    doc_payload = {
        "structData": {
            "title": "Manual Oficial de Trámites Ciudadanos del Gobierno de El Salvador (RNPN, DGME, SERTRACEN)",
            "category": "tramites_ciudadanos_goes",
        },
        "content": {
            "mimeType": "text/plain",
            "rawBytes": base64.b64encode(corpus_text.encode("utf-8")).decode("ascii"),
        },
    }
    r_doc = requests.get(doc_url, headers=headers, timeout=30)
    if r_doc.status_code == 200:
      print(f"[terraform-ge-workaround] Document '{doc_id}' already indexed in DataStore '{data_store_id}'.")
    else:
      create_doc_url = f"{base_url}/{parent}/dataStores/{data_store_id}/branches/default_branch/documents?documentId={doc_id}"
      r_create_doc = requests.post(create_doc_url, headers=headers, json=doc_payload, timeout=60)
      r_create_doc.raise_for_status()
      print(f"[terraform-ge-workaround] Indexed official GOES document '{doc_id}' into '{data_store_id}'.")

  # 3. Ensure Gemini Enterprise Engine (APP_TYPE_INTRANET)
  eng_url = f"{base_url}/{parent}/engines/{engine_id}"
  r_eng = requests.get(eng_url, headers=headers, timeout=30)
  if r_eng.status_code == 200:
    print(f"[terraform-ge-workaround] Gemini Enterprise Engine '{engine_id}' already exists (200 OK).")
  else:
    create_eng_url = f"{base_url}/{parent}/engines?engineId={engine_id}"
    eng_payload = {
        "displayName": f"Gemini Enterprise - GOES ({project_id})",
        "solutionType": "SOLUTION_TYPE_SEARCH",
        "industryVertical": "GENERIC",
        "appType": "APP_TYPE_INTRANET",
        "dataStoreIds": [data_store_id],
        "searchEngineConfig": {
            "searchTier": "SEARCH_TIER_ENTERPRISE",
            "searchAddOns": ["SEARCH_ADD_ON_LLM"],
        },
    }
    r_create_eng = requests.post(create_eng_url, headers=headers, json=eng_payload, timeout=60)
    r_create_eng.raise_for_status()
    op = r_create_eng.json()
    if "name" in op and "/operations/" in op["name"]:
      wait_lro(base_url, op, project_id)
    print(f"[terraform-ge-workaround] Created Gemini Enterprise Engine '{engine_id}'.")

  # 4. Verify default_assistant under the Engine
  asst_url = f"{base_url}/{parent}/engines/{engine_id}/assistants/default_assistant"
  r_asst = requests.get(asst_url, headers=headers, timeout=30)
  if r_asst.status_code == 200:
    print(f"[terraform-ge-workaround] Assistant 'default_assistant' is active on '{engine_id}'.")


def destroy_ge_infrastructure(
    project_id: str,
    location: str,
    engine_id: str,
    data_store_id: str,
) -> None:
  """Deletes Gemini Enterprise Engine and indexed document on `terraform destroy` so the DataStore can be cleanly destroyed."""
  headers = get_headers(project_id)
  base_url = (
      "https://discoveryengine.googleapis.com/v1alpha"
      if location == "global"
      else f"https://{location}-discoveryengine.googleapis.com/v1alpha"
  )
  parent = f"projects/{project_id}/locations/{location}/collections/default_collection"

  # 1. Delete Gemini Enterprise Engine (detaches DataStore so google_discovery_engine_data_store can be destroyed)
  eng_url = f"{base_url}/{parent}/engines/{engine_id}"
  r_eng = requests.get(eng_url, headers=headers, timeout=30)
  if r_eng.status_code == 200:
    print(f"[terraform-ge-workaround][destroy] Deleting Gemini Enterprise Engine '{engine_id}'...")
    r_del_eng = requests.delete(eng_url, headers=headers, timeout=60)
    if r_del_eng.status_code in (200, 204):
      op = r_del_eng.json() if r_del_eng.text.strip() else {}
      if "name" in op and "/operations/" in op["name"]:
        wait_lro(base_url, op, project_id)
    print(f"[terraform-ge-workaround][destroy] Deleted Engine '{engine_id}'.")
  else:
    print(f"[terraform-ge-workaround][destroy] Engine '{engine_id}' already absent (404).")

  # 2. Delete Corpus Document from DataStore
  doc_id = "manual-oficial-tramites-goes-2026"
  doc_url = f"{base_url}/{parent}/dataStores/{data_store_id}/branches/default_branch/documents/{doc_id}"
  r_del_doc = requests.delete(doc_url, headers=headers, timeout=30)
  print(f"[terraform-ge-workaround][destroy] Deleted document '{doc_id}' (status={r_del_doc.status_code}).")


def main() -> None:
  parser = argparse.ArgumentParser(description="Ensure or destroy Gemini Enterprise v1alpha resources for Terraform")
  parser.add_argument("--project-id", required=True)
  parser.add_argument("--location", default="global")
  parser.add_argument("--engine-id", required=True)
  parser.add_argument("--data-store-id", required=True)
  parser.add_argument(
      "--corpus-file",
      default="agents/sv_citizen_assistant/corpus/manual_oficial_tramites_sv.md",
  )
  parser.add_argument("--destroy", action="store_true", help="Tear down Engine and Document during terraform destroy")
  args = parser.parse_args()
  try:
    if args.destroy:
      destroy_ge_infrastructure(
          project_id=args.project_id,
          location=args.location,
          engine_id=args.engine_id,
          data_store_id=args.data_store_id,
      )
    else:
      ensure_ge_infrastructure(
          project_id=args.project_id,
          location=args.location,
          engine_id=args.engine_id,
          data_store_id=args.data_store_id,
          corpus_file=args.corpus_file,
      )
  except Exception as exc:  # pylint: disable=broad-except
    print(f"[ERROR] {exc}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
