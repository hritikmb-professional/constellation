#!/usr/bin/env python3
"""
Compliance Agent: Evaluate control satisfaction over a change's blast radius.

This lens answers: "Does this change cross a control boundary, and if so, are
the required safeguards in place?" It is a composition consumer — it reads the
subgraph Impact already materialized (which files/areas are in the blast
radius) rather than re-traversing Orbit.

Two classes of control are evaluated:
  - STRUCTURAL controls (fully evaluable from the code graph): does the blast
    radius touch a sensitive boundary (security, auth, redaction, payments)?
  - SDLC controls (need GitLab metadata at deploy): non-author approval,
    passing pipeline. When that metadata is absent (local Orbit), the control
    is reported as NEEDS_GITLAB_DATA — honestly, not as a silent pass.
"""

import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict, field
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Control boundaries detectable directly from file paths in the code graph.
SENSITIVE_BOUNDARIES = {
    "security": ["security", "auth", "redaction", "secret", "token", "crypto"],
    "payments": ["payment", "billing", "invoice"],
}


@dataclass
class ControlResult:
    """The outcome of evaluating a single compliance control."""
    name: str
    status: str   # PASS, FAIL, NEEDS_GITLAB_DATA
    detail: str


@dataclass
class ComplianceVerdict:
    """The verdict from the Compliance lens."""
    event_id: str
    crossed_boundaries: List[str]          # boundary categories the change touches
    boundary_files: List[str]              # the specific files that triggered them
    controls: List[ControlResult]
    violations: int                        # count of FAIL controls
    needs_data: int                        # count of NEEDS_GITLAB_DATA controls
    compliant: bool                        # True only if every control PASSes
    risk_level: str                        # LOW, MEDIUM, HIGH
    composed_from_impact: bool = True
    confidence: float = 0.0


class ComplianceAgent:
    """Evaluate standing compliance controls over Impact's materialized subgraph."""

    def analyze_subgraph(
        self, event_id: str, shared_subgraph, mr_meta: Optional[Dict[str, Any]] = None
    ) -> ComplianceVerdict:
        """
        Evaluate controls for a materialized blast-radius subgraph.

        Args:
            event_id: the originating event id.
            shared_subgraph: a MaterializedSubgraph from the Impact agent.
            mr_meta: optional MR metadata from GitLab (approvals, pipeline).
        """
        mr_meta = mr_meta or {}

        # Structural: which sensitive boundaries does the blast radius cross?
        boundary_files: List[str] = []
        categories: set = set()
        for svc in shared_subgraph.affected_services:
            path = (svc.full_path or "").lower()
            for category, keywords in SENSITIVE_BOUNDARIES.items():
                if any(kw in path for kw in keywords):
                    categories.add(category)
                    boundary_files.append(svc.full_path)
                    break

        crossed = sorted(categories)
        logger.info(f"Compliance: blast radius crosses boundaries {crossed or 'none'}")

        controls = self._evaluate_controls(crossed, mr_meta)
        violations = sum(1 for c in controls if c.status == "FAIL")
        needs_data = sum(1 for c in controls if c.status == "NEEDS_GITLAB_DATA")
        compliant = all(c.status == "PASS" for c in controls)

        risk_level = self._risk_level(crossed, violations, needs_data)
        # Fully evaluable (no missing data) -> high confidence; otherwise honest dip.
        confidence = 0.9 if needs_data == 0 else 0.6

        verdict = ComplianceVerdict(
            event_id=event_id,
            crossed_boundaries=crossed,
            boundary_files=sorted(set(boundary_files))[:5],
            controls=controls,
            violations=violations,
            needs_data=needs_data,
            compliant=compliant,
            risk_level=risk_level,
            confidence=confidence,
        )
        return verdict

    def _evaluate_controls(self, crossed: List[str], mr_meta: Dict[str, Any]) -> List[ControlResult]:
        """Evaluate the control set given the boundaries crossed and MR metadata."""
        if not crossed:
            return [
                ControlResult(
                    name="Sensitive boundary crossing",
                    status="PASS",
                    detail="Blast radius does not touch a sensitive control boundary.",
                )
            ]

        # The umbrella control's status is DERIVED from its dependent SDLC
        # controls (added below): FAIL if any actually failed, PASS if all
        # passed, otherwise NEEDS_GITLAB_DATA — we don't call "unverified" a
        # "violation". It is filled in after the dependents are evaluated.
        controls = [
            ControlResult(
                name="Sensitive boundary crossing",
                status="NEEDS_GITLAB_DATA",
                detail=f"Change reaches {', '.join(crossed)} code - stricter controls apply.",
            )
        ]

        # SDLC control: non-author approval on sensitive change.
        approvals = mr_meta.get("approvals")
        if approvals is None:
            controls.append(ControlResult(
                "Non-author approval on sensitive change", "NEEDS_GITLAB_DATA",
                "Approval data not available locally; enforced via GitLab at deploy.",
            ))
        else:
            non_author = bool(approvals.get("non_author_approved"))
            controls.append(ControlResult(
                "Non-author approval on sensitive change",
                "PASS" if non_author else "FAIL",
                "Non-author approval present." if non_author else "Missing non-author approval.",
            ))

        # SDLC control: passing pipeline before merge.
        pipeline = mr_meta.get("pipeline_status")
        if pipeline is None:
            controls.append(ControlResult(
                "Passing pipeline before merge", "NEEDS_GITLAB_DATA",
                "Pipeline status not available locally; enforced via GitLab at deploy.",
            ))
        else:
            controls.append(ControlResult(
                "Passing pipeline before merge",
                "PASS" if pipeline == "passed" else "FAIL",
                f"Pipeline status: {pipeline}.",
            ))

        # Derive the umbrella control's status from its dependents.
        dependents = controls[1:]
        if any(c.status == "FAIL" for c in dependents):
            controls[0] = ControlResult(
                "Sensitive boundary crossing", "FAIL",
                f"Change reaches {', '.join(crossed)} and a required control failed.",
            )
        elif dependents and all(c.status == "PASS" for c in dependents):
            controls[0] = ControlResult(
                "Sensitive boundary crossing", "PASS",
                f"Change reaches {', '.join(crossed)} but required controls are satisfied.",
            )
        # else: stays NEEDS_GITLAB_DATA (crossing detected, controls unverified locally)
        return controls

    def _risk_level(self, crossed: List[str], violations: int, needs_data: int) -> str:
        """Compliance risk: violations are high; unverified sensitive crossings are medium."""
        if violations > 0:
            return "HIGH"
        if crossed and needs_data > 0:
            return "MEDIUM"
        if crossed:
            return "LOW"  # crossed but all controls satisfied
        return "LOW"


def format_verdict_as_markdown(verdict: ComplianceVerdict) -> str:
    """Format the compliance verdict as GitLab markdown."""
    status_icon = {"PASS": "[OK]", "FAIL": "[X]", "NEEDS_GITLAB_DATA": "[?]"}
    header = "compliant" if verdict.compliant else f"{verdict.violations} violation(s)"
    md = f"""## Compliance

**Boundaries crossed:** {', '.join(verdict.crossed_boundaries) or 'none'}
**Status:** {verdict.risk_level} risk — {header}

"""
    for c in verdict.controls:
        md += f"- {status_icon.get(c.status, '[?]')} **{c.name}** — {c.detail}\n"

    if verdict.boundary_files:
        md += "\nTriggering files:\n"
        for f in verdict.boundary_files:
            md += f"- `{f}`\n"

    md += f"\n_Composed from Impact's materialized subgraph; confidence {verdict.confidence:.0%}_\n"
    return md


if __name__ == "__main__":
    from dataclasses import dataclass as _dc

    @_dc
    class _Svc:
        full_path: str

    @_dc
    class _Subgraph:
        affected_services: list

    sub = _Subgraph(affected_services=[
        _Svc("crates/integration-tests/tests/server/data_correctness/security.rs"),
        _Svc("crates/integration-tests/tests/server/redaction.rs"),
    ])
    v = ComplianceAgent().analyze_subgraph("mr-demo", sub)
    print(format_verdict_as_markdown(v))
