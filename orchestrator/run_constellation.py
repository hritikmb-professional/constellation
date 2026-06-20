#!/usr/bin/env python3
"""
Constellation entry point: run the FULL composition on one event.

This is the single deployable entry the flow should invoke. It constructs the
real Orchestrator with a real Orbit client and runs the same in-process
composition the integration tests exercise: Impact materializes the subgraph,
Ownership / Compliance / Provenance consume it, risk is blended, and the
Decision Gate is applied. The verdict markdown is what gets posted to the MR.

Why a single in-process entry (not one flow step per agent): the composition
passes a live MaterializedSubgraph object between lenses. That object cannot be
serialized between separate flow steps, so the honest way to preserve the
"materialize once, consume many" guarantee is to run the orchestrator in one
process. The flow's job is to gather the event and post the returned comment.

Usage:
    python run_constellation.py '<event-json>'
    echo '<event-json>' | python run_constellation.py
"""

import json
import sys
import os

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ORCH_DIR)
sys.path.insert(0, ORCH_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared"))

from orchestrator import Orchestrator


def _make_orbit_client():
    """Use the real Orbit client if the binary is present; else the mock."""
    binary = os.path.join(PROJECT_ROOT, "bin", "orbit.exe")
    if not os.path.exists(binary):
        binary = os.path.join(PROJECT_ROOT, "bin", "orbit")
    try:
        from orbit_real_client import RealOrbitClient
        if os.path.exists(binary):
            client = RealOrbitClient(orbit_binary_path=binary)
            if client.health_check():
                return client, "real"
    except Exception:
        pass
    from orbit_mock import MockOrbitClient
    return MockOrbitClient(), "mock"


def run(event):
    """Run the full orchestrator on an event and return (verdict, markdown, mode)."""
    client, mode = _make_orbit_client()
    orchestrator = Orchestrator(client, gitlab_client=None)
    verdict = orchestrator.handle_event(event)
    markdown = orchestrator.format_as_markdown(verdict)
    return verdict, markdown, mode


def main():
    if len(sys.argv) > 1:
        event = json.loads(sys.argv[1])
    else:
        event = json.load(sys.stdin)

    from dataclasses import asdict
    verdict, markdown, mode = run(event)
    print(json.dumps({
        "orbit_mode": mode,
        "recommended_action": verdict.recommended_action,
        "overall_risk_level": verdict.overall_risk_level,
        "verdict": asdict(verdict),
        "markdown": markdown,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
