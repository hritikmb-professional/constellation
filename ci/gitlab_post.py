#!/usr/bin/env python3
"""
Post a Constellation verdict as a note (comment) on the merge request.

Uses GitLab's CI-predefined variables and a project access token supplied as a
masked CI variable `CONSTELLATION_TOKEN`. The token is read from the
environment — it is never hard-coded and never logged.

To avoid stacking a new comment on every pipeline run, this updates an existing
Constellation note (found by a hidden marker) when one is present, and creates
one otherwise.
"""

import json
import os
import urllib.request
import urllib.error

MARKER = "<!-- constellation-verdict -->"


def _api(method: str, path: str, payload: dict = None):
    base = os.environ["CI_API_V4_URL"].rstrip("/")
    token = os.environ["CONSTELLATION_TOKEN"]
    url = f"{base}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else None)


def post_or_update_verdict(markdown: str) -> int:
    # CI_MERGE_REQUEST_PROJECT_ID is the target project (where the MR lives).
    # Falls back to CI_PROJECT_ID for non-fork pipelines.
    project = os.environ.get("CI_MERGE_REQUEST_PROJECT_ID") or os.environ["CI_PROJECT_ID"]
    iid = os.environ["CI_MERGE_REQUEST_IID"]
    body = f"{MARKER}\n{markdown}"

    notes_path = f"/projects/{project}/merge_requests/{iid}/notes"

    # Look for an existing Constellation note to update in place.
    try:
        _, notes = _api("GET", f"{notes_path}?per_page=100")
        existing = next((n for n in (notes or []) if MARKER in (n.get("body") or "")), None)
    except Exception:
        existing = None

    if existing:
        status, _ = _api("PUT", f"{notes_path}/{existing['id']}", {"body": body})
    else:
        status, _ = _api("POST", notes_path, {"body": body})
    return status


if __name__ == "__main__":
    import sys
    md = sys.stdin.read() or "## Constellation\n(no verdict supplied)"
    print("posted, status", post_or_update_verdict(md))
