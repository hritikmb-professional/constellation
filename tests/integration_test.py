#!/usr/bin/env python3
"""
Integration Test: Full Constellation Pipeline

Tests the composition model:
- MR event → Impact agent → materialized subgraph
- Subgraph → Provenance agent → composed verdict
- Output → formatted markdown with evidence trails
"""

import sys
import json
import os
from datetime import datetime

# Add parent dirs to path
test_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(test_dir)

sys.path.insert(0, os.path.join(project_root, "agents/impact"))
sys.path.insert(0, os.path.join(project_root, "agents/provenance"))
sys.path.insert(0, os.path.join(project_root, "orchestrator"))
sys.path.insert(0, os.path.join(project_root, "shared"))

from impact_agent import ImpactAgent, format_verdict_as_markdown as format_impact
from provenance_agent import ProvenanceAgent, format_verdict_as_markdown as format_provenance
from orbit_mock import MockOrbitClient

# Try to use real Orbit client, fall back to mock
try:
    from orbit_real_client import RealOrbitClient
    orbit_binary = os.path.join(project_root, "bin", "orbit.exe")
    if os.path.exists(orbit_binary):
        _orbit_client = RealOrbitClient(orbit_binary_path=orbit_binary)
        if _orbit_client.health_check():
            DefaultOrbitClient = RealOrbitClient
            DEFAULT_ORBIT_BINARY = orbit_binary
            print("[INFO] Using REAL Orbit database")
        else:
            DefaultOrbitClient = MockOrbitClient
            print("[INFO] Real Orbit not available, falling back to MOCK")
    else:
        DefaultOrbitClient = MockOrbitClient
        print("[INFO] Orbit binary not found, using MOCK")
except ImportError:
    DefaultOrbitClient = MockOrbitClient
    print("[INFO] Real client not available, using MOCK")

from orchestrator import Orchestrator


def test_impact_agent_with_mock_orbit():
    """Test Impact agent with Orbit data (real or mock)."""
    print("\n" + "=" * 80)
    print("TEST 1: Impact Agent (Blast Radius)")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
    else:
        orbit_client = DefaultOrbitClient()
    agent = ImpactAgent(orbit_client)

    # Use real symbols from Orbit repo when testing with real Orbit
    if DefaultOrbitClient == RealOrbitClient:
        changed_symbols = ["allow_all", "compile"]
    else:
        changed_symbols = ["process_config", "validate_input"]

    mr_event = {
        "mr_id": "mr-123",
        "changed_symbols": changed_symbols,
        "mr_title": "Refactor Orbit functions",
        "mr_url": "https://gitlab.com/example/project/-/merge_requests/123",
    }

    verdict = agent.analyze_mr(mr_event)

    print(f"\nVerdict: {verdict}")
    print("\nFormatted as Markdown:")
    print(format_impact(verdict))

    # Assertions - flexible for both mock and real data
    # Real Orbit shows much higher dependents (510 transitive for allow_all+compile)
    # Mock shows fixed 14
    if DefaultOrbitClient == RealOrbitClient:
        assert verdict.total_dependents > 50, f"Expected >50 real dependents, got {verdict.total_dependents}"
        # Real data: file-level services and module-level owners, counts vary.
        assert len(verdict.affected_services) >= 3, f"Expected >=3 real services, got {len(verdict.affected_services)}"
        assert len(verdict.affected_owners) >= 1, f"Expected >=1 real owner area, got {len(verdict.affected_owners)}"
        # Cut-vertex analysis must find real structural chokepoints with non-zero
        # isolation impact (distinct from keystone fan-in).
        assert len(verdict.chokepoints) >= 1, "Expected >=1 structural chokepoint on real data"
        assert verdict.chokepoints[0].isolated > 0, "Top chokepoint should isolate >0 definitions"
        # Keystones must carry a REAL PageRank centrality rank (computed over the
        # whole call graph), not just a caller-count rank.
        assert verdict.keystone_symbols, "Expected keystones on allow_all+compile"
        assert all(k.pagerank_rank > 0 for k in verdict.keystone_symbols), (
            "Every keystone should have a real PageRank centrality rank"
        )
    else:
        assert verdict.total_dependents == 14, f"Expected 14 mock dependents, got {verdict.total_dependents}"
        assert len(verdict.affected_services) == 3, f"Expected 3 services, got {len(verdict.affected_services)}"
        assert len(verdict.affected_owners) == 2, f"Expected 2 owners, got {len(verdict.affected_owners)}"
    assert verdict.confidence >= 0.90, f"Expected confidence >= 0.90, got {verdict.confidence}"

    print("\n[PASS] TEST 1 PASSED")
    return verdict


def test_provenance_agent_with_mock_orbit():
    """Test Provenance agent with Orbit data (real or mock)."""
    print("\n" + "=" * 80)
    print("TEST 2: Provenance Agent (Vulnerability Lineage)")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
        # Use a symbol that exists in the index so the code half of the lineage
        # (finding -> symbol -> definition) resolves from the REAL graph.
        affected_symbol = "allow_all"
    else:
        orbit_client = DefaultOrbitClient()
        affected_symbol = "process_config"
    agent = ProvenanceAgent(orbit_client)

    finding_event = {
        "finding_id": "cve-2026-1234",
        "title": "RCE in yaml.load()",
        "severity": "CRITICAL",
        "cvss_score": 9.1,
        "affected_symbol": affected_symbol,
    }

    verdict = agent.analyze_finding(finding_event)

    print(f"\nVerdict: {verdict}")
    print("\nFormatted as Markdown:")
    print(format_provenance(verdict))

    # Assertions
    assert verdict.finding_id == "cve-2026-1234"
    assert verdict.severity == "CRITICAL"
    assert len(verdict.lineage_chain) == 5, f"Expected 5-step lineage, got {len(verdict.lineage_chain)}"
    assert len(verdict.exposure_scope) == 2, f"Expected 2 exposed services, got {len(verdict.exposure_scope)}"
    assert verdict.confidence >= 0.95, f"Expected high confidence, got {verdict.confidence}"

    # On real Orbit, the code half of the lineage must be REAL (resolved from
    # the graph), while the SDLC half (MR, author) stays representative.
    if DefaultOrbitClient == RealOrbitClient:
        def_step = next(s for s in verdict.lineage_chain if s.entity_type == "definition")
        assert def_step.metadata.get("data_source") == "real", "definition step should be real on real Orbit"
        assert ".rs" in (def_step.metadata.get("file") or ""), (
            f"expected a real file path, got {def_step.metadata.get('file')}"
        )
        author_step = next(s for s in verdict.lineage_chain if s.entity_type == "author")
        assert author_step.metadata.get("data_source") == "representative", (
            "author step should be representative (no SDLC tables locally)"
        )

    print("\n[PASS] TEST 2 PASSED")
    return verdict


def test_orchestrator_composition():
    """Test Orchestrator composing Impact + Provenance verdicts."""
    print("\n" + "=" * 80)
    print("TEST 3: Orchestrator (Verdict Composition)")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
    else:
        orbit_client = DefaultOrbitClient()
    orchestrator = Orchestrator(orbit_client, gitlab_client=None)

    # Use a symbol that ACTUALLY EXISTS in the index so the test exercises real
    # data, not a vacuous 0-dependent result.
    changed = ["allow_all"] if DefaultOrbitClient == RealOrbitClient else ["process_config"]

    # Event: MR opened that touches vulnerable code
    event = {
        "event_id": "mr-123",
        "event_type": "mr_opened",
        "timestamp": datetime.utcnow().isoformat(),
        "payload": {
            "mr_id": "mr-123",
            "changed_symbols": changed,
            "mr_title": "Refactor a high-impact function",
        },
    }

    composed_verdict = orchestrator.handle_event(event)

    print(f"\nComposed verdict: {composed_verdict}")
    print("\nFormatted as Markdown:")
    markdown_output = orchestrator.format_as_markdown(composed_verdict)
    print(markdown_output)

    # Assertions
    assert composed_verdict.event_id == "mr-123"
    assert composed_verdict.event_type == "mr_opened"
    assert composed_verdict.impact_verdict is not None, "Impact verdict missing"
    assert composed_verdict.overall_risk_level in [
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
        "UNKNOWN",
    ]
    assert len(composed_verdict.evidence_trails) > 0, "No evidence trails"

    # On real Orbit, this MUST be a non-vacuous result (would fail on 0).
    if DefaultOrbitClient == RealOrbitClient:
        assert composed_verdict.impact_verdict["total_dependents"] > 50, (
            f"Expected real transitive blast radius, got {composed_verdict.impact_verdict['total_dependents']}"
        )
        assert len(composed_verdict.impact_verdict["affected_services"]) > 0, "No affected services on real data"
        assert composed_verdict.ownership_verdict is not None, "Ownership did not run on real data"
        assert composed_verdict.compliance_verdict is not None, "Compliance did not run on real data"

    print("\n[PASS] TEST 3 PASSED")
    return composed_verdict


def test_full_scenario_mr_with_vulnerability():
    """Full scenario: MR touches code with a known vulnerability."""
    print("\n" + "=" * 80)
    print("FULL SCENARIO: MR touches vulnerable code")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
    else:
        orbit_client = DefaultOrbitClient()
    orchestrator = Orchestrator(orbit_client, gitlab_client=None)

    # Use a real symbol so the Impact half exercises real Orbit data.
    changed = ["allow_all"] if DefaultOrbitClient == RealOrbitClient else ["process_config"]

    # Step 1: Developer opens MR that changes a high-impact function
    print("\n1. Developer opens MR #123")
    mr_event = {
        "event_id": "mr-123",
        "event_type": "mr_opened",
        "timestamp": datetime.utcnow().isoformat(),
        "payload": {
            "mr_id": "mr-123",
            "changed_symbols": changed,
            "mr_title": "Refactor a high-impact function",
            "mr_url": "https://gitlab.com/...",
        },
    }

    verdict = orchestrator.handle_event(mr_event)
    print("\n2. Constellation Impact analysis:")
    print(f"   - Blast radius: {verdict.impact_verdict['total_dependents']} dependents")
    print(f"   - Affected services: {len(verdict.impact_verdict['affected_services'])}")

    # On real Orbit the impact half must be non-vacuous.
    if DefaultOrbitClient == RealOrbitClient:
        assert verdict.impact_verdict["total_dependents"] > 50, (
            f"Expected real blast radius, got {verdict.impact_verdict['total_dependents']}"
        )

    # Step 2: Security team flags a vulnerability in process_config
    print("\n3. Security team reports CVE-2026-1234 in process_config")
    finding_event = {
        "event_id": "cve-2026-1234",
        "event_type": "finding_created",
        "timestamp": datetime.utcnow().isoformat(),
        "payload": {
            "finding_id": "cve-2026-1234",
            "title": "RCE in yaml.load()",
            "severity": "CRITICAL",
            "cvss_score": 9.1,
            "affected_symbol": "process_config",
        },
    }

    verdict2 = orchestrator.handle_event(finding_event)
    print("\n4. Constellation Provenance analysis:")
    print(f"   - Lineage: {len(verdict2.provenance_verdict['lineage_chain'])} steps")
    print(f"   - Exposure: {len(verdict2.provenance_verdict['exposure_scope'])} services")
    print(f"   - Introduced by: {verdict2.provenance_verdict['introducing_author']}")

    # Step 3: Composed verdict
    print("\n5. COMPOSED VERDICT:")
    print(f"   Overall Risk Level: {verdict2.overall_risk_level}")
    print(f"   Evidence Trails: {len(verdict2.evidence_trails)}")

    print("\n[INFO] Full Markdown Output:")
    print(orchestrator.format_as_markdown(verdict2))

    print("\n[PASS] FULL SCENARIO PASSED")


def test_shared_context_composition():
    """
    Prove the composition moat: Provenance consumes the subgraph Impact
    materialized, rather than re-querying Orbit independently.
    """
    print("\n" + "=" * 80)
    print("TEST 4: Shared-Context Composition (the moat)")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
        changed_symbols = ["allow_all"]
    else:
        orbit_client = DefaultOrbitClient()
        changed_symbols = ["process_config"]

    orchestrator = Orchestrator(orbit_client, gitlab_client=None)

    # One event: an MR that changes a symbol which ALSO carries a known finding.
    event = {
        "event_id": "mr-compose",
        "event_type": "mr_opened",
        "timestamp": datetime.utcnow().isoformat(),
        "payload": {
            "mr_id": "mr-compose",
            "changed_symbols": changed_symbols,
            "mr_title": "Refactor a symbol that has an open CVE",
            "findings": [
                {
                    "finding_id": "cve-2026-9999",
                    "title": "Injection in changed symbol",
                    "severity": "HIGH",
                    "cvss_score": 8.2,
                    "affected_symbol": changed_symbols[0],
                }
            ],
        },
    }

    composed = orchestrator.handle_event(event)

    print("\nFormatted as Markdown:")
    print(orchestrator.format_as_markdown(composed))

    # Both lenses ran from one event
    assert composed.impact_verdict is not None, "Impact verdict missing"
    assert composed.provenance_verdict is not None, "Provenance verdict missing"

    # The proof: Provenance consumed Impact's materialized subgraph
    assert composed.provenance_verdict["composed_from_impact"] is True, (
        "Provenance did NOT consume Impact's subgraph — composition is not real"
    )

    # Ownership lens also runs from the same shared subgraph
    if DefaultOrbitClient == RealOrbitClient:
        assert composed.ownership_verdict is not None, "Ownership verdict missing"
        assert composed.ownership_verdict["composed_from_impact"] is True, (
            "Ownership did NOT consume Impact's subgraph"
        )
        assert composed.ownership_verdict["bus_factor"] >= 1, "Ownership bus_factor not computed"
        assert any("Ownership consumed" in t for t in composed.evidence_trails), (
            "Ownership composition not recorded in evidence trail"
        )

        # Compliance lens also runs from the same shared subgraph
        assert composed.compliance_verdict is not None, "Compliance verdict missing"
        assert composed.compliance_verdict["composed_from_impact"] is True, (
            "Compliance did NOT consume Impact's subgraph"
        )
        # allow_all's blast radius reaches security/redaction files -> boundary crossed
        assert "security" in composed.compliance_verdict["crossed_boundaries"], (
            f"Expected security boundary crossing, got {composed.compliance_verdict['crossed_boundaries']}"
        )
        assert any("Compliance consumed" in t for t in composed.evidence_trails), (
            "Compliance composition not recorded in evidence trail"
        )

    # Exposure scope must match the services Impact materialized (same context)
    impact_services = {s["project_id"] for s in composed.impact_verdict["affected_services"]}
    prov_services = {s["project_id"] for s in composed.provenance_verdict["exposure_scope"]}
    assert prov_services == impact_services, (
        f"Exposure {prov_services} != Impact subgraph {impact_services} — not shared context"
    )

    # Evidence trail records the composition
    assert any("consumed Impact's subgraph" in t for t in composed.evidence_trails), (
        "Composition not recorded in evidence trail"
    )

    print("\n[PASS] TEST 4 PASSED — Provenance consumed Impact's materialized subgraph")
    return composed


def test_edit_semantics_gate():
    """
    The fix for the headline false positive: the SAME central symbol must get a
    DIFFERENT verdict depending on what the edit actually does. A comment must
    de-escalate; a contract change must escalate.
    """
    print("\n" + "=" * 80)
    print("TEST 5: Edit-Semantics Gate (what changed, not just where)")
    print("=" * 80)

    if DefaultOrbitClient == RealOrbitClient:
        orbit_client = RealOrbitClient(orbit_binary_path=DEFAULT_ORBIT_BINARY)
        symbols = ["allow_all", "compile"]
    else:
        orbit_client = DefaultOrbitClient()
        symbols = ["process_config"]
    orchestrator = Orchestrator(orbit_client, gitlab_client=None)

    def verdict_for(edit_class, danger, cb):
        ev = {
            "event_id": "gate", "event_type": "mr_opened",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": {
                "mr_id": "gate", "changed_symbols": symbols, "mr_title": "x",
                "edit_semantics": {
                    "edit_class": edit_class, "edit_danger": danger,
                    "contract_break_symbols": cb, "note": "",
                },
            },
        }
        return orchestrator.handle_event(ev)

    cosmetic = verdict_for("cosmetic", 0.0, [])
    contract = verdict_for("contract-break", 1.0, symbols)
    print(f"\ncosmetic -> {cosmetic.recommended_action} ({cosmetic.overall_risk_level})")
    print(f"contract-break -> {contract.recommended_action} ({contract.overall_risk_level})")

    if DefaultOrbitClient == RealOrbitClient:
        # The whole point: a comment on a keystone must NOT block.
        assert cosmetic.recommended_action == "AUTO_APPROVE", (
            f"cosmetic edit on a keystone should AUTO_APPROVE, got {cosmetic.recommended_action}"
        )
        assert contract.recommended_action in ("BLOCK", "SENIOR_REVIEW"), (
            f"contract change should escalate, got {contract.recommended_action}"
        )
        assert cosmetic.recommended_action != contract.recommended_action, (
            "same symbol must get different verdicts by edit class"
        )

    print("\n[PASS] TEST 5 PASSED — verdict is gated by what changed, not just centrality")
    return cosmetic, contract


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "#" * 80)
    print("# CONSTELLATION INTEGRATION TESTS")
    print("#" * 80)

    try:
        test_impact_agent_with_mock_orbit()
        test_provenance_agent_with_mock_orbit()
        test_orchestrator_composition()
        test_full_scenario_mr_with_vulnerability()
        test_shared_context_composition()
        test_edit_semantics_gate()

        print("\n" + "#" * 80)
        print("# ALL TESTS PASSED [OK]")
        print("#" * 80)
        print("\nConclusion:")
        print("- Impact agent computes accurate blast radius")
        print("- Provenance agent traces vulnerability lineage")
        print("- Orchestrator composes verdicts with shared context")
        print("- Provenance consumes Impact's materialized subgraph (composition proven)")
        print("- System ready for real Orbit integration")
        print()

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
