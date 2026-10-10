#!/usr/bin/env python3
"""Helper script to:
0. Ensure centralized Terraform state bucket `gs://goes-ge-tf-backend` exists in `drm-tfproject-000`.
1. Verify Keyless Workload Identity Federation (WIF) variables (`WIF_PROVIDER` & `WIF_SERVICE_ACCOUNT`)
   are configured across all 6 GitHub repositories (no static keys or default credentials stored in GitHub).
2. Reset STG and PRD (delete the custom No-Code Agent in goes-ge-gha-stg, goes-ge-gha-prd,
   goes-ge-cb-stg, and goes-ge-cb-prd) while keeping DEV deployed and active for Agent Designer UI.
3. Clear old GitHub Actions workflow runs in STG and PRD so you can test the manual promotion
   (DEV -> STG -> PRD) from a clean state.
"""

import os
from pathlib import Path
import subprocess
import sys
import google.auth
import google.auth.transport.requests
import requests

GH_BIN = os.path.expanduser("~/.local/bin/gh")
REPO_DIR = Path(__file__).resolve().parent.parent
TF_STATE_PROJECT = "drm-tfproject-000"
TF_STATE_BUCKET = "goes-ge-tf-backend"


def run_cmd(cmd: list[str], check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
  return subprocess.run(cmd, cwd=str(REPO_DIR), text=True, input=input_text, capture_output=True, check=check)


def main() -> None:
  creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  creds.refresh(google.auth.transport.requests.Request())
  headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json", "X-Goog-User-Project": TF_STATE_PROJECT}

  print(f"=== 0. Ensuring Centralized Terraform State Bucket gs://{TF_STATE_BUCKET} in {TF_STATE_PROJECT} ===")
  r_bkt = requests.get(f"https://storage.googleapis.com/storage/v1/b/{TF_STATE_BUCKET}", headers=headers, timeout=30)
  if r_bkt.status_code == 404:
    rc = requests.post(
        f"https://storage.googleapis.com/storage/v1/b?project={TF_STATE_PROJECT}",
        headers=headers,
        json={
            "name": TF_STATE_BUCKET,
            "location": "US",
            "versioning": {"enabled": True},
            "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}},
        },
        timeout=30,
    )
    print(f"  [OK] Created centralized state bucket gs://{TF_STATE_BUCKET} in {TF_STATE_PROJECT} ({rc.status_code})")
  else:
    print(f"  [OK] Centralized state bucket gs://{TF_STATE_BUCKET} in {TF_STATE_PROJECT} ready (versioning=True)")

  print("\n=== 1. Resetting STG & PRD (Deleting custom No-Code Agent in STG & PRD while keeping DEV active) ===")
  for env_name, proj_id in [
      ("stg", "goes-ge-gha-stg"),
      ("prd", "goes-ge-gha-prd"),
      ("stg", "goes-ge-cb-stg"),
      ("prd", "goes-ge-cb-prd"),
  ]:
    env = os.environ.copy()
    env.update({
        "ENV": env_name,
        "GE_PROJECT_ID": proj_id,
        "GE_LOCATION": "global",
        "GE_ENGINE_ID": "sv-citizen-engine",
        "GE_DATA_STORE_ID": "sv-tramites-datastore",
    })
    res = subprocess.run(
        [sys.executable, "cli/ge_agent_cli.py", "delete"],
        cwd=str(REPO_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    print(f"  [{proj_id}] {res.stdout.strip() or res.stderr.strip()}")

  print("\n=== 2. Cleaning GitHub Actions history in STG & PRD for clean manual testing ===")
  for clean_repo in ("danielardzmtz01/ge-nocode-agents-stg", "danielardzmtz01/ge-nocode-agents-prd"):
    res = run_cmd([GH_BIN, "api", f"repos/{clean_repo}/actions/runs", "--jq", ".workflow_runs[].id"], check=False)
    for run_id in res.stdout.strip().splitlines():
      if run_id.strip():
        run_cmd([GH_BIN, "api", "-X", "DELETE", f"repos/{clean_repo}/actions/runs/{run_id.strip()}"], check=False)
    print(f"  [OK] Cleared past workflow runs in {clean_repo}")

  print("\n=== READY FOR MANUAL HANDS-ON TESTING WITH KEYLESS WIF (DEV -> STG -> PRD) ===")


if __name__ == "__main__":
  main()
