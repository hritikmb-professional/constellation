#!/usr/bin/env python3
"""
Verdict Composer: compose pre-computed lens outputs into the final verdict.

This is a thin adapter for environments (e.g. a Duo Agent Platform flow step)
that already hold the individual lens dicts and just need them composed. It
delegates to the SAME risk model, Decision Gate, and markdown formatter as the
tested Orchestrator (orchestrator.py) so the deployed path is identical to the
path exercised by the integration tests — not a divergent, weaker copy.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import Orchestrator, ComposedVerdict


def compose(
    impact=None,
    provenance=None,
    ownership=None,
    compliance=None,
    event_type="mr_opened",
    event_id="unknown",
):
    """
    Build a ComposedVerdict from pre-computed lens dicts and run the REAL
    orchestrator scoring (blended risk + Decision Gate) + formatter over it.
    """
    verdict = ComposedVerdict(
        event_id=event_id,
        event_type=event_type,
        timestamp="",
        impact_verdict=impact,
        provenance_verdict=provenance,
        ownership_verdict=ownership,
        compliance_verdict=compliance,
    )

    # Reconstruct evidence trail from whatever lenses are present.
    if impact:
        verdict.evidence_trails.append(
            f"Impact: {impact.get('total_dependents', 0)} transitive dependents"
        )
    if ownership:
        verdict.evidence_trails.append(
            f"Ownership: bus factor {ownership.get('bus_factor', 0)}"
        )
    if compliance:
        verdict.evidence_trails.append(
            f"Compliance: {', '.join(compliance.get('crossed_boundaries', [])) or 'no'} boundary crossing"
        )
    if provenance:
        verdict.evidence_trails.append(
            f"Provenance: lineage {len(provenance.get('lineage_chain', []))} steps"
        )

    # Delegate to the tested orchestrator logic — no separate risk model here.
    orch = Orchestrator(orbit_client=None, gitlab_client=None)
    orch._compute_overall_risk(verdict)
    orch._compute_decision_gate(verdict)
    markdown = orch.format_as_markdown(verdict)
    return verdict, markdown


def main():
    """Entry point: reads JSON {impact, provenance, ownership, compliance, event_type} and emits verdict + markdown."""
    try:
        if len(sys.argv) > 1:
            input_data = json.loads(sys.argv[1])
        else:
            input_data = json.load(sys.stdin)

        verdict, markdown = compose(
            impact=input_data.get("impact"),
            provenance=input_data.get("provenance"),
            ownership=input_data.get("ownership"),
            compliance=input_data.get("compliance"),
            event_type=input_data.get("event_type", "unknown"),
            event_id=input_data.get("event_id", "unknown"),
        )

        from dataclasses import asdict
        print(json.dumps({"verdict": asdict(verdict), "markdown": markdown}, indent=2))

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON parse error: {e}"}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Composition failed: {e}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
