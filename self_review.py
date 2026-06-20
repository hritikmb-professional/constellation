#!/usr/bin/env python3
"""
Self-review: Constellation analyzes its OWN codebase.

We index this very repository with Orbit, then ask Constellation to review a
change to one of its own most-reused functions - first as a harmless body edit,
then as a contract break - and print the verdict it would post on itself.

It is the strongest possible honesty check: the tool is held to its own gate.

    BACKTEST_ORBIT=/path/to/orbit python self_review.py

(The CI pipeline does this for real on every Constellation merge request: it
indexes the repo it runs on and posts the verdict. This script reproduces that
locally and is non-destructive - the indexed graph is additive, keyed per repo.)
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("shared", "agents/impact", "agents/provenance", "agents/ownership",
            "agents/compliance", "orchestrator", "ci"):
    sys.path.insert(0, os.path.join(HERE, sub))

from orbit_real_client import RealOrbitClient   # noqa: E402
from orchestrator import Orchestrator           # noqa: E402

# A real, Constellation-unique function with the highest internal fan-in. Using
# a unique name keeps the blast radius scoped to this repo even when the graph
# also holds other indexed projects.
TARGET = "_to_int"


def ensure_indexed(orbit_bin):
    """Index this repo into the local graph (additive - won't drop other repos)."""
    out = subprocess.run([orbit_bin, "index", HERE], capture_output=True, text=True)
    if out.returncode != 0:
        print(f"WARN: indexing returned {out.returncode}: {out.stderr[:200]}", file=sys.stderr)


def review(orch, klass, danger, contract_syms):
    event = {
        "event_id": "self", "event_type": "mr_opened",
        "payload": {
            "mr_id": "self-review", "changed_symbols": [TARGET],
            "mr_title": f"self-review: {klass} change to {TARGET}()",
            "edit_semantics": {
                "edit_class": klass, "edit_danger": danger,
                "contract_break_symbols": contract_syms,
                "signatures": {}, "files": ["shared/orbit_real_client.py"],
                "note": f"{klass} (self-review)",
            },
        },
    }
    return orch.handle_event(event)


def main():
    orbit_bin = os.environ.get("BACKTEST_ORBIT", "orbit")
    ensure_indexed(orbit_bin)
    client = RealOrbitClient(orbit_binary_path=orbit_bin)
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2
    orch = Orchestrator(client, gitlab_client=None)

    print("=" * 72)
    print(f"CONSTELLATION SELF-REVIEW  -  target: {TARGET}() (its own code)")
    print("=" * 72)

    body = review(orch, "body-edit", 0.5, [])
    brk = review(orch, "contract-break", 1.0, [TARGET])

    bdeps = (body.impact_verdict or {}).get("total_dependents", 0)
    print(f"\nSame function, same internal blast radius ({bdeps} dependents).")
    print("The verdict moves only with WHAT the change does:\n")
    print(f"  body edit (logic only)   -> {body.recommended_action}")
    print(f"  contract break (signature) -> {brk.recommended_action}")

    print("\n" + "-" * 72)
    print("Full verdict Constellation would post on its own contract-break MR:")
    print("-" * 72 + "\n")
    print(orch.format_as_markdown(brk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
