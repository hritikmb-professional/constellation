#!/usr/bin/env python3
"""
CI entry point: analyze the current merge request and post the verdict.

Flow:
  1. Resolve the MR's diff base (target branch merge-base) from CI env vars.
  2. Extract the changed symbols from the diff via Orbit line ranges.
  3. Run the full four-lens orchestrator (Impact materializes the subgraph;
     Ownership / Compliance / Provenance consume it; blended risk + Decision Gate).
  4. Post the verdict markdown as an MR comment.

Assumes the repo has already been indexed (`orbit index .`) in a prior CI step,
and that `ORBIT_BIN` points at the Orbit binary (defaults to `orbit` on PATH).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for sub in ("shared", "agents/impact", "agents/provenance", "agents/ownership",
            "agents/compliance", "orchestrator", "ci"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from orbit_real_client import RealOrbitClient   # noqa: E402
from orchestrator import Orchestrator           # noqa: E402
from changed_symbols import changed_symbols      # noqa: E402
from edit_semantics import classify_changes      # noqa: E402
from gitlab_post import post_or_update_verdict   # noqa: E402


def _diff_base() -> str:
    # GitLab provides the precise merge-base for MR pipelines.
    base = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    if base:
        return base
    target = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    if target:
        return f"origin/{target}"
    return "HEAD~1"


def main() -> int:
    orbit_bin = os.environ.get("ORBIT_BIN", "orbit")
    client = RealOrbitClient(orbit_binary_path=orbit_bin)
    if not client.health_check():
        print("ERROR: Orbit not available / repo not indexed", file=sys.stderr)
        return 2

    base = _diff_base()
    symbols = changed_symbols(client, base)
    print(f"Changed symbols ({len(symbols)}): {symbols}")

    # Classify WHAT changed (cosmetic / body-edit / contract-break) so risk is
    # gated by the edit, not just the centrality of the symbol touched.
    edit = classify_changes(base)
    print(f"Edit class: {edit['edit_class']} (danger {edit['edit_danger']}) — {edit['note']}")

    if not symbols:
        md = ("## Constellation\n\nNo code definitions changed in this MR "
              "(or none resolved to the indexed graph). Nothing to analyze.")
        if os.environ.get("CI_MERGE_REQUEST_IID"):
            post_or_update_verdict(md)
        return 0

    payload = {
        "mr_id": os.environ.get("CI_MERGE_REQUEST_IID", "local"),
        "changed_symbols": symbols,
        "mr_title": os.environ.get("CI_MERGE_REQUEST_TITLE", ""),
        "edit_semantics": edit,
    }

    # The Provenance lens answers "where does THIS vulnerability reach?" so it
    # only runs when a security finding is attached. Real findings come from a
    # GitLab security scan at deploy. For a demo, CONSTELLATION_DEMO_FINDING=1
    # attaches a CLEARLY-ILLUSTRATIVE finding on the top changed symbol so all
    # four lenses appear; the exposure it computes is real (it reuses Impact's
    # subgraph), only the finding itself is a demo input — labeled as such.
    if os.environ.get("CONSTELLATION_DEMO_FINDING") == "1" and symbols:
        target = symbols[0]
        payload["findings"] = [{
            "finding_id": "DEMO (illustrative — not a real vulnerability)",
            "title": f"Illustrative finding on `{target}` to exercise the Provenance lens",
            "severity": "HIGH",
            "cvss_score": 0.0,
            "affected_symbol": target,
        }]

    event = {
        "event_id": os.environ.get("CI_MERGE_REQUEST_IID", "local"),
        "event_type": "mr_opened",
        "payload": payload,
    }

    orchestrator = Orchestrator(client, gitlab_client=None)
    verdict = orchestrator.handle_event(event)
    markdown = orchestrator.format_as_markdown(verdict)
    print(f"Decision: {verdict.recommended_action} | Risk: {verdict.overall_risk_level}")

    # Always write the verdict as a CI artifact for inspection.
    try:
        with open(os.path.join(ROOT, "constellation_verdict.md"), "w", encoding="utf-8") as fh:
            fh.write(markdown)
    except Exception:
        pass

    in_mr = bool(os.environ.get("CI_MERGE_REQUEST_IID"))
    have_token = bool(os.environ.get("CONSTELLATION_TOKEN"))
    if in_mr and have_token:
        status = post_or_update_verdict(markdown)
        print(f"Posted verdict to MR, HTTP {status}")
    else:
        if in_mr and not have_token:
            print(
                "\n[!] CONSTELLATION_TOKEN not set — verdict computed but NOT posted.\n"
                "    Add it under Settings -> CI/CD -> Variables (api scope, Masked, "
                "Protected OFF), then re-run.\n"
            )
        print("----- CONSTELLATION VERDICT -----")
        print(markdown)

    # Optional: make the pipeline fail (red) when the gate says BLOCK, so the
    # Decision Gate is an actual control. Toggle with CONSTELLATION_ENFORCE.
    if os.environ.get("CONSTELLATION_ENFORCE") == "1" and verdict.recommended_action == "BLOCK":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
