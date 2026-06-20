#!/usr/bin/env python3
"""
Constellation Orchestrator: Compose Impact and Provenance verdicts.

Routes events -> Impact -> (materialized subgraph) -> Provenance
Composes verdicts -> outputs markdown with evidence trails.
"""

import json
import sys
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging

# Import agents
orchestrator_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(orchestrator_dir)

sys.path.insert(0, os.path.join(project_root, "agents/impact"))
sys.path.insert(0, os.path.join(project_root, "agents/provenance"))
sys.path.insert(0, os.path.join(project_root, "agents/ownership"))
sys.path.insert(0, os.path.join(project_root, "agents/compliance"))

from impact_agent import ImpactAgent
from provenance_agent import ProvenanceAgent
from ownership_agent import OwnershipAgent
from compliance_agent import ComplianceAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ComposedVerdict:
    """Final composed verdict from all agents."""
    event_id: str
    event_type: str  # "mr_opened", "finding_created"
    timestamp: str
    impact_verdict: Optional[Dict[str, Any]] = None
    provenance_verdict: Optional[Dict[str, Any]] = None
    compliance_verdict: Optional[Dict[str, Any]] = None
    ownership_verdict: Optional[Dict[str, Any]] = None
    overall_risk_level: str = "UNKNOWN"  # LOW, MEDIUM, HIGH, CRITICAL
    recommended_action: str = "REVIEW_REQUIRED"  # AUTO_APPROVE, REVIEW_REQUIRED, SENIOR_REVIEW, BLOCK
    action_reason: str = ""
    evidence_trails: List[str] = None

    def __post_init__(self):
        if self.evidence_trails is None:
            self.evidence_trails = []


class Orchestrator:
    """
    Orchestrator: Route events, run agents, compose verdicts.

    Flow:
    1. Event arrives (MR opened, finding created)
    2. Route to appropriate agent(s)
    3. Impact runs first, materializes subgraph
    4. Pass subgraph to Provenance (if applicable)
    5. Compose verdicts, format output
    6. Post to GitLab (MR comment, work item, etc.)
    """

    def __init__(self, orbit_client, gitlab_client):
        """Initialize with Orbit and GitLab clients."""
        self.orbit_client = orbit_client
        self.gitlab_client = gitlab_client
        self.impact_agent = ImpactAgent(orbit_client)
        self.provenance_agent = ProvenanceAgent(orbit_client, gitlab_client)
        self.ownership_agent = OwnershipAgent()
        self.compliance_agent = ComplianceAgent()

    def handle_event(self, event: Dict[str, Any]) -> ComposedVerdict:
        """
        Handle a GitLab event and compose a verdict.

        Args:
            event: GitLab webhook event, including:
                - event_type: "merge_request.opened", "vulnerability.created", etc.
                - payload: event-specific data

        Returns:
            ComposedVerdict with analyzed findings.
        """
        event_type = event.get("event_type", "unknown")
        event_id = event.get("event_id", "unknown")
        payload = event.get("payload", {})

        logger.info(f"Orchestrator: handling {event_type} event {event_id}")

        composed = ComposedVerdict(
            event_id=event_id,
            event_type=event_type,
            timestamp=event.get("timestamp", ""),
        )

        # Route to handlers
        if "merge_request.opened" in event_type or event_type == "mr_opened":
            self._handle_mr_opened(payload, composed)

        elif "vulnerability.created" in event_type or event_type == "finding_created":
            self._handle_finding_created(payload, composed)

        # Compute overall risk level, then derive the actionable decision gate
        self._compute_overall_risk(composed)
        self._compute_decision_gate(composed)

        logger.info(f"Orchestrator: verdict ready for {event_id}")
        return composed

    def _handle_mr_opened(self, payload: Dict[str, Any], verdict: ComposedVerdict):
        """
        Handle MR opened event.

        Impact runs first and materializes a blast-radius subgraph. If the MR
        touches symbols that carry known security findings, Provenance runs
        next and CONSUMES that subgraph rather than re-querying Orbit — this is
        the shared-context composition that makes Constellation more than four
        independent tools.
        """
        logger.info("Orchestrator: handling MR opened")

        # Run Impact agent -> materializes the shared subgraph.
        impact_result = self.impact_agent.analyze_mr(payload)
        verdict.impact_verdict = asdict(impact_result)
        verdict.evidence_trails.append(
            f"Impact materialized blast-radius subgraph: "
            f"{impact_result.total_dependents} dependents across "
            f"{len(impact_result.affected_services)} services"
        )
        logger.info(f"Orchestrator: Impact found {impact_result.total_dependents} dependents")

        subgraph = self.impact_agent.last_subgraph

        # Composition: Ownership consumes the same materialized subgraph to score
        # bus-factor risk — no second Orbit traversal.
        if subgraph and subgraph.affected_owners:
            ownership_result = self.ownership_agent.analyze_subgraph(
                impact_result.event_id, subgraph
            )
            verdict.ownership_verdict = asdict(ownership_result)
            verdict.evidence_trails.append(
                f"Ownership consumed Impact's subgraph: bus factor {ownership_result.bus_factor}, "
                f"{ownership_result.concentration:.0%} concentrated in {ownership_result.top_area}"
            )

        # Composition: Compliance consumes the same subgraph to evaluate whether
        # the blast radius crosses a control boundary — again, no re-traversal.
        if subgraph and subgraph.affected_services:
            compliance_result = self.compliance_agent.analyze_subgraph(
                impact_result.event_id, subgraph, mr_meta=payload.get("mr_meta")
            )
            verdict.compliance_verdict = asdict(compliance_result)
            verdict.evidence_trails.append(
                f"Compliance consumed Impact's subgraph: boundaries crossed = "
                f"{', '.join(compliance_result.crossed_boundaries) or 'none'}, "
                f"{compliance_result.violations} violation(s)"
            )

        # Composition: route any findings on the changed code through Provenance,
        # handing it the subgraph Impact just materialized.
        findings = payload.get("findings", [])
        for finding in findings:
            prov_result = self.provenance_agent.analyze_finding(
                finding, shared_subgraph=subgraph
            )
            verdict.provenance_verdict = asdict(prov_result)
            if prov_result.composed_from_impact:
                verdict.evidence_trails.append(
                    f"Provenance consumed Impact's subgraph: vulnerability exposure "
                    f"scoped to {len(prov_result.exposure_scope)} services without re-querying Orbit"
                )
            else:
                verdict.evidence_trails.append(
                    "Provenance analysis completed (independent query — symbol not in subgraph)"
                )

    def _handle_finding_created(self, payload: Dict[str, Any], verdict: ComposedVerdict):
        """Handle vulnerability finding created event: run Provenance agent."""
        logger.info("Orchestrator: handling finding created")

        # Run Provenance agent
        provenance_result = self.provenance_agent.analyze_finding(payload)
        verdict.provenance_verdict = asdict(provenance_result)
        verdict.evidence_trails.append("Provenance analysis completed")

        logger.info(f"Orchestrator: Provenance traced lineage, exposure in {len(provenance_result.exposure_scope)} services")

    def _compute_overall_risk(self, verdict: ComposedVerdict):
        """
        Compute overall risk level from component verdicts.

        Unlike a naive average of failure rates, this folds in the *magnitude*
        of the blast radius and keystone exposure -- a change touching 510
        dependents or a single point of failure is high risk even when the
        base failure rate looks low.
        """
        risk_scores = []

        if verdict.impact_verdict:
            impact = verdict.impact_verdict
            risk_scores.append(impact.get("change_failure_rate", 0.0))

            # Blast-radius magnitude: large fan-out is inherently risky.
            dependents = impact.get("total_dependents", 0)
            if dependents >= 300:
                risk_scores.append(0.85)
            elif dependents >= 100:
                risk_scores.append(0.65)
            elif dependents >= 25:
                risk_scores.append(0.45)
            else:
                risk_scores.append(0.20)

            # Keystone exposure: any single point of failure escalates risk.
            if impact.get("keystone_symbols"):
                risk_scores.append(0.90)

        if verdict.provenance_verdict:
            prov_severity = verdict.provenance_verdict.get("severity", "LOW")
            severity_scores = {"CRITICAL": 0.95, "HIGH": 0.80, "MEDIUM": 0.60, "LOW": 0.30}
            risk_scores.append(severity_scores.get(prov_severity, 0.50))

        if verdict.ownership_verdict:
            own_level = verdict.ownership_verdict.get("risk_level", "LOW")
            own_scores = {"HIGH": 0.85, "MEDIUM": 0.60, "LOW": 0.25}
            risk_scores.append(own_scores.get(own_level, 0.40))

        if verdict.compliance_verdict:
            comp_level = verdict.compliance_verdict.get("risk_level", "LOW")
            comp_scores = {"HIGH": 0.90, "MEDIUM": 0.55, "LOW": 0.25}
            risk_scores.append(comp_scores.get(comp_level, 0.40))

        if not risk_scores:
            verdict.overall_risk_level = "UNKNOWN"
            return

        # Weight the worst signal heavily so a single critical factor dominates.
        peak_risk = max(risk_scores)
        avg_risk = sum(risk_scores) / len(risk_scores)
        blended_risk = 0.6 * peak_risk + 0.4 * avg_risk

        if blended_risk >= 0.80:
            verdict.overall_risk_level = "CRITICAL"
        elif blended_risk >= 0.60:
            verdict.overall_risk_level = "HIGH"
        elif blended_risk >= 0.40:
            verdict.overall_risk_level = "MEDIUM"
        else:
            verdict.overall_risk_level = "LOW"

        logger.info(
            f"Orchestrator: overall risk = {verdict.overall_risk_level} "
            f"(blended {blended_risk:.2f}, peak {peak_risk:.2f})"
        )

    def _compute_decision_gate(self, verdict: ComposedVerdict):
        """
        Turn the risk assessment into an actionable merge decision.

        This is what makes Constellation a control, not just a report: every
        verdict ends in a recommendation a CI gate or reviewer can act on.
        """
        level = verdict.overall_risk_level
        keystones = []
        # No impact analysis => no confidence. Default LOW (not 1.0) so a missing
        # Impact verdict can never satisfy the high-confidence AUTO_APPROVE branch.
        confidence = 0.0
        has_impact = verdict.impact_verdict is not None
        if has_impact:
            keystones = verdict.impact_verdict.get("keystone_symbols") or []
            confidence = verdict.impact_verdict.get("confidence", 0.0)

        if level == "CRITICAL":
            action, reason = "BLOCK", "Critical risk: do not merge without sign-off."
        elif level == "HIGH" or keystones:
            action = "SENIOR_REVIEW"
            reason = (
                "Keystone single-point-of-failure touched; senior review required."
                if keystones
                else "High blast radius; senior reviewer required."
            )
        elif level == "MEDIUM":
            action, reason = "REVIEW_REQUIRED", "Moderate impact; standard review required."
        elif level == "LOW" and has_impact and confidence >= 0.90:
            action, reason = "AUTO_APPROVE", "Low impact, high confidence; safe to auto-merge."
        else:
            action, reason = "REVIEW_REQUIRED", "Incomplete signal; default to human review."

        verdict.recommended_action = action
        verdict.action_reason = reason
        logger.info(f"Orchestrator: decision gate -> {action} ({reason})")

    def format_as_markdown(self, verdict: ComposedVerdict) -> str:
        """Format composed verdict as GitLab markdown."""
        action_labels = {
            "AUTO_APPROVE": "[OK] AUTO-APPROVE",
            "REVIEW_REQUIRED": "[~] REVIEW REQUIRED",
            "SENIOR_REVIEW": "[!] SENIOR REVIEW REQUIRED",
            "BLOCK": "[X] BLOCK MERGE",
        }
        gate = action_labels.get(verdict.recommended_action, verdict.recommended_action)

        md = f"""# Constellation Analysis

**Event:** {verdict.event_type} ({verdict.event_id})
**Risk Level:** {verdict.overall_risk_level}

> ## Decision: {gate}
> {verdict.action_reason}

---

"""

        # Add Impact section if available
        if verdict.impact_verdict:
            impact_data = verdict.impact_verdict
            md += f"""## Impact Analysis

Blast Radius: **{impact_data['total_dependents']}** transitive dependents across **{len(impact_data['affected_services'])}** services

"""
            for svc in impact_data.get("affected_services", []):
                # Show the distinguishing path (the crate alone repeats across rows).
                label = svc.get("full_path") or svc.get("project_name", "")
                crit = " [!] critical path" if svc.get("is_critical_path") else ""
                md += f"- `{label}` ({svc['affected_definitions']} affected){crit}\n"

            for k in impact_data.get("keystone_symbols", []):
                pr = f", PageRank centrality #{k['pagerank_rank']}" if k.get("pagerank_rank") else ""
                md += (
                    f"- [!] Keystone `{k['name']}` "
                    f"({k['inbound_calls']} callers, caller-count #{k['centrality_rank']}{pr})\n"
                )

            chokepoints = impact_data.get("chokepoints", [])
            if chokepoints:
                md += "\n**Chokepoints (cut vertices - failure isolates downstream code):**\n"
                for c in chokepoints:
                    tag = " (changed by this MR)" if c.get("is_changed") else ""
                    md += f"- `{c['name']}` isolates **{c['isolated']}** definitions if it fails{tag}\n"

            md += f"""
Change-Failure Risk: **{impact_data['change_failure_rate']:.0%}**
Confidence: {impact_data['confidence']:.0%}

---

"""

        # Add Ownership section if available
        if verdict.ownership_verdict:
            own = verdict.ownership_verdict
            md += f"""## Ownership Risk

Bus factor: **{own['bus_factor']}** owning area(s) | Concentration: **{own['concentration']:.0%}** in `{own['top_area']}`
Risk: **{own['risk_level']}** - {own['risk_note']}

"""
            for area in own.get("owning_areas", [])[:5]:
                md += f"- `{area['name']}` - {area['affected_definitions']} ({area['share']:.0%})\n"
            md += "\n---\n\n"

        # Add Compliance section if available
        if verdict.compliance_verdict:
            comp = verdict.compliance_verdict
            status_icon = {"PASS": "[OK]", "FAIL": "[X]", "NEEDS_GITLAB_DATA": "[?]"}
            header = "compliant" if comp["compliant"] else f"{comp['violations']} violation(s)"
            md += f"""## Compliance

Boundaries crossed: **{', '.join(comp['crossed_boundaries']) or 'none'}** | {comp['risk_level']} risk - {header}

"""
            for c in comp.get("controls", []):
                md += f"- {status_icon.get(c['status'], '[?]')} **{c['name']}** - {c['detail']}\n"
            md += "\n---\n\n"

        # Add Provenance section if available
        if verdict.provenance_verdict:
            prov_data = verdict.provenance_verdict
            composed = prov_data.get("composed_from_impact")
            # Pull the real definition step (resolved from the graph) if present.
            real_def_step = next(
                (s for s in prov_data.get("lineage_chain", [])
                 if s.get("entity_type") == "definition"
                 and (s.get("metadata") or {}).get("data_source") == "real"),
                None,
            )
            md += f"""## Vulnerability Analysis

**Finding:** {prov_data['finding_id']} - {prov_data['finding_title']}
**Severity:** {prov_data['severity']} (CVSS {prov_data['cvss_score']})

"""
            if real_def_step:
                meta = real_def_step.get("metadata", {})
                md += (
                    f"**Code (real, from graph):** `{prov_data['affected_symbol']}` at "
                    f"`{meta.get('file')}:{meta.get('lines')}` "
                    f"({meta.get('inbound_callers', 0)} inbound callers)\n\n"
                )
                md += (
                    "> [?] **Introducing MR / author are representative** - Orbit's local index "
                    "has no SDLC tables; these resolve from GitLab merge-request/author edges at deploy.\n\n"
                )
            else:
                md += (
                    "> [?] **Lineage is representative data** (finding -> introducing MR -> author). "
                    "Orbit's local index has no SDLC tables; real lineage resolves at deploy.\n\n"
                )

            md += f"""**Lineage:** {prov_data['affected_symbol']} -> MR {prov_data['introducing_mr_id']} (rep) -> {prov_data['introducing_author']} (rep)

**Exposure:** Reachable in {len(prov_data['exposure_scope'])} services{' (real - composed from Impact subgraph)' if composed else ''}
"""

            for svc in prov_data.get("exposure_scope", []):
                deployed = " [OK]" if svc["is_deployed"] else " [!]"
                label = svc.get("full_path") or svc.get("project_name", "")
                md += f"- {deployed} `{label}`\n"

            if prov_data.get("critical_path"):
                md += "\n [!] **CRITICAL PATH**\n"

            md += f"""
**Confidence:** {prov_data['confidence']:.0%}

---

"""

        md += f"""## Evidence Trail

{chr(10).join(f"- {trail}" for trail in verdict.evidence_trails)}

---

_Generated by Constellation: Graph-Native DevOps Intelligence on GitLab Orbit_
"""

        return md


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: orchestrator.py <event.json>")
        sys.exit(1)

    # Load event from file or stdin
    event_file = sys.argv[1]
    try:
        with open(event_file, "r") as f:
            event = json.load(f)
    except FileNotFoundError:
        event = json.loads(event_file)

    # Create orchestrator (mock clients for now)
    orchestrator = Orchestrator(orbit_client=None, gitlab_client=None)

    # Process event
    verdict = orchestrator.handle_event(event)

    # Output
    print(orchestrator.format_as_markdown(verdict))


if __name__ == "__main__":
    main()
