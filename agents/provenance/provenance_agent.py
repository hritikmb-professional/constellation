#!/usr/bin/env python3
"""
Provenance Agent: Trace vulnerability lineage and exposure.

Input: Finding event (vulnerability finding)
Output: Lineage (finding → code → MR → author) + exposure scope
"""

import json
import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ProvenanceChain:
    """A step in the provenance chain."""
    step: int
    entity_type: str  # "finding", "symbol", "definition", "mr", "author"
    entity_id: str
    entity_name: str
    metadata: Dict[str, Any]  # e.g., {"title", "severity", "date", "username"}


@dataclass
class ExposedService:
    """A service that is exposed to the vulnerability."""
    project_id: str
    project_name: str
    full_path: str
    is_reachable: bool
    is_deployed: bool
    last_deployment: Optional[str]


@dataclass
class ProvenanceVerdict:
    """The verdict from the Provenance agent."""
    event_id: str
    finding_id: str
    finding_title: str
    severity: str
    cvss_score: float
    lineage_chain: List[ProvenanceChain]
    affected_symbol: str
    introducing_mr_id: str
    introducing_author: str
    exposure_scope: List[ExposedService]
    critical_path: bool
    remediation_work_item_id: Optional[str]
    confidence: float
    composed_from_impact: bool = False
    composition_note: str = ""


class ProvenanceAgent:
    """
    Provenance Agent: Trace vulnerability lineage and exposure.

    Implements the Provenance lens: given a finding, trace back to
    the introducing MR and author, determine exposure, and recommend
    remediation.
    """

    def __init__(self, orbit_client, work_item_client=None):
        """Initialize with Orbit and work-item clients."""
        self.orbit_client = orbit_client
        self.work_item_client = work_item_client

    def analyze_finding(
        self, finding_event: Dict[str, Any], shared_subgraph=None
    ) -> ProvenanceVerdict:
        """
        Analyze a vulnerability finding and trace its lineage.

        Args:
            finding_event: Finding event from GitLab, including:
                - finding_id: vulnerability ID
                - title: vulnerability title
                - severity: HIGH, CRITICAL, etc.
                - affected_file: file path
                - affected_symbol: function/class name (if available)
            shared_subgraph: Optional MaterializedSubgraph from the Impact
                agent. When the finding's affected symbol is a root of this
                subgraph, exposure is derived from Impact's already-materialized
                blast radius instead of re-querying Orbit. This is the
                shared-context composition path.

        Returns:
            ProvenanceVerdict with full lineage and exposure analysis.
        """
        finding_id = finding_event.get("finding_id")
        affected_symbol = finding_event.get("affected_symbol", "Unknown")
        logger.info(f"Provenance: analyzing finding {finding_id}")

        # Step 1: Query lineage (finding → symbol → MR → author)
        lineage = self._query_lineage(finding_event)
        logger.info(f"Provenance: traced lineage with {len(lineage)} steps")

        # Step 2: Determine exposure scope.
        # Composition path: if Impact has already materialized a subgraph that
        # roots at this symbol, the vulnerability's exposure IS that blast
        # radius — reuse it instead of re-traversing the graph.
        composed = bool(
            shared_subgraph is not None
            and shared_subgraph.covers_symbol(affected_symbol)
        )
        composition_note = ""
        if composed:
            exposure = self._exposure_from_subgraph(shared_subgraph)
            composition_note = (
                f"Exposure derived from Impact's materialized subgraph "
                f"({shared_subgraph.total_dependents} dependents) — Orbit not re-queried."
            )
            logger.info(f"Provenance: COMPOSED on Impact subgraph — {composition_note}")
        else:
            exposure = self._query_exposure_scope(finding_event)
            logger.info(f"Provenance: found exposure in {len(exposure)} services (independent query)")

        # Step 3: Determine if critical path
        critical_path = self._check_critical_path(exposure)
        logger.info(f"Provenance: critical_path = {critical_path}")

        # Step 4: Create remediation work item
        remediation_id = self._create_remediation_work_item(finding_event, lineage, exposure)
        if remediation_id:
            logger.info(f"Provenance: created work item {remediation_id}")

        # Step 5: Compute confidence. Shared context is internally consistent,
        # so composition raises confidence (no cross-query reconciliation gap).
        confidence = self._compute_confidence(lineage, exposure)
        if composed:
            confidence = min(1.0, confidence + 0.01)

        verdict = ProvenanceVerdict(
            event_id=finding_id,
            finding_id=finding_id,
            finding_title=finding_event.get("title", "Unknown"),
            severity=finding_event.get("severity", "UNKNOWN"),
            cvss_score=finding_event.get("cvss_score", 0.0),
            lineage_chain=lineage,
            affected_symbol=affected_symbol,
            introducing_mr_id=lineage[-2].entity_id if len(lineage) >= 3 else "Unknown",
            introducing_author=lineage[-1].entity_name if lineage else "Unknown",
            exposure_scope=exposure,
            critical_path=critical_path,
            remediation_work_item_id=remediation_id,
            confidence=confidence,
            composed_from_impact=composed,
            composition_note=composition_note,
        )

        return verdict

    def _exposure_from_subgraph(self, shared_subgraph) -> List[ExposedService]:
        """
        Convert Impact's materialized blast-radius services into the
        vulnerability's exposure scope.

        This is the composition: the set of services reachable from the
        changed symbol (computed by Impact) is exactly the set of services
        exposed to a vulnerability in that symbol.
        """
        exposure: List[ExposedService] = []
        for svc in shared_subgraph.affected_services:
            exposure.append(
                ExposedService(
                    project_id=svc.project_id,
                    project_name=svc.project_name,
                    full_path=svc.full_path,
                    is_reachable=True,  # reachability is implied by subgraph membership
                    is_deployed=True,
                    last_deployment=None,
                )
            )
        return exposure

    def _query_lineage(self, finding_event: Dict[str, Any]) -> List[ProvenanceChain]:
        """
        Trace finding -> symbol -> definition -> MR -> author.

        The code half (finding -> symbol -> definition) is resolved from the
        REAL code graph when an Orbit client is available: the symbol is mapped
        to its actual definition with real file path, line span, kind, and
        caller count. The SDLC half (introducing MR -> author) needs tables not
        present in Orbit Local (gl_merge_request, gl_user), so those steps are
        representative until deploy-time SDLC enrichment. Every step is tagged
        with metadata['data_source'] = 'real' | 'representative'.
        """
        logger.info("Provenance: querying lineage")

        finding_id = finding_event.get("finding_id", "unknown")
        title = finding_event.get("title", "Unknown finding")
        severity = finding_event.get("severity", "UNKNOWN")
        cvss = finding_event.get("cvss_score", 0.0)
        symbol = finding_event.get("affected_symbol", "Unknown")

        chain: List[ProvenanceChain] = [
            ProvenanceChain(
                step=1,
                entity_type="finding",
                entity_id=finding_id,
                entity_name=f"{finding_id}: {title}",
                metadata={"severity": severity, "cvss_score": cvss, "data_source": "real"},
            )
        ]

        # Steps 2-3: resolve the symbol to its real definition from the graph.
        real_def = None
        if self.orbit_client:
            try:
                res = self.orbit_client.query("symbol_definition", symbol=symbol)
                real_def = (res or {}).get("definition")
            except Exception as e:
                logger.warning(f"Provenance: symbol resolution failed ({e}); using representative")

        if real_def and real_def.get("file_path"):
            chain.append(ProvenanceChain(
                step=2, entity_type="symbol", entity_id=symbol, entity_name=f"{symbol}()",
                metadata={
                    "file": real_def["file_path"], "line": real_def["start_line"],
                    "data_source": "real",
                },
            ))
            chain.append(ProvenanceChain(
                step=3, entity_type="definition",
                entity_id=real_def.get("fqn") or symbol,
                entity_name=real_def.get("fqn") or f"{symbol}()",
                metadata={
                    "file": real_def["file_path"],
                    "lines": f"{real_def['start_line']}-{real_def['end_line']}",
                    "kind": real_def.get("definition_type"),
                    "inbound_callers": real_def.get("inbound_callers", 0),
                    "data_source": "real",
                },
            ))
        else:
            # No graph resolution (offline/mock, or symbol absent) -> representative.
            chain.append(ProvenanceChain(
                step=2, entity_type="symbol", entity_id=symbol, entity_name=f"{symbol}()",
                metadata={"file": "src/config/parser.rs", "line": 234, "data_source": "representative"},
            ))
            chain.append(ProvenanceChain(
                step=3, entity_type="definition", entity_id="def-456", entity_name=f"{symbol}()",
                metadata={"project": "knowledge-graph", "file": "src/config/parser.rs",
                          "data_source": "representative"},
            ))

        # Steps 4-5: introducing MR + author require SDLC tables absent from
        # Orbit Local -> representative until deploy-time enrichment.
        chain.append(ProvenanceChain(
            step=4, entity_type="mr", entity_id="mr-2456", entity_name="!2456",
            metadata={"title": "Add YAML config parser", "date": "2026-03-15",
                      "author_id": "alice", "data_source": "representative"},
        ))
        chain.append(ProvenanceChain(
            step=5, entity_type="author", entity_id="alice", entity_name="alice@example.com",
            metadata={"name": "Alice Chen", "team": "platform", "data_source": "representative"},
        ))
        return chain

    def _query_exposure_scope(self, finding_event: Dict[str, Any]) -> List[ExposedService]:
        """
        Query Orbit for services that are exposed to the vulnerability.

        Uses shared/queries.sql Query 2c.
        """
        logger.info("Provenance: querying exposure scope")

        # Mock result
        return [
            ExposedService(
                project_id="p1",
                project_name="api-service",
                full_path="microservices/api-service",
                is_reachable=True,
                is_deployed=True,
                last_deployment="2026-06-15T10:30:00Z",
            ),
            ExposedService(
                project_id="p2",
                project_name="config-service",
                full_path="microservices/config-service",
                is_reachable=True,
                is_deployed=True,
                last_deployment="2026-06-14T15:45:00Z",
            ),
        ]

    def _check_critical_path(self, exposure: List[ExposedService]) -> bool:
        """Determine if any exposed service is in the critical path."""
        # Heuristic: if any service name contains "payment", "billing", or "auth", mark as critical
        critical_keywords = ["payment", "billing", "auth", "security"]
        for svc in exposure:
            if any(kw in svc.project_name.lower() for kw in critical_keywords):
                return True
        return False

    def _create_remediation_work_item(
        self, finding_event: Dict[str, Any], lineage: List[ProvenanceChain], exposure: List[ExposedService]
    ) -> Optional[str]:
        """
        Create a work item for remediation, scoped by exposure.

        In production, would use GitLab work-item API.
        For now, return a mock ID.
        """
        logger.info("Provenance: creating remediation work item")

        # Mock: work item ID
        return "work-item-457"

    def _compute_confidence(self, lineage: List[ProvenanceChain], exposure: List[ExposedService]) -> float:
        """Compute confidence in the provenance analysis."""
        confidence = 0.99

        # Decrease confidence if lineage is incomplete
        if len(lineage) < 5:
            confidence -= 0.1 * (5 - len(lineage))

        # Decrease confidence if we can't determine deployment status
        if any(s.last_deployment is None for s in exposure):
            confidence -= 0.05

        return max(0.0, min(1.0, confidence))


def format_verdict_as_mermaid_graph(verdict: ProvenanceVerdict) -> str:
    """Format provenance chain as mermaid graph (uniform node ids, valid edges).

    Representative (non-graph) steps are suffixed with '(rep)' so the diagram
    distinguishes real graph-resolved nodes from deploy-time-pending ones.
    """
    lines = ["graph LR"]

    # Uniform node ids (N1..Nk) so the edges below always reference real nodes.
    for step in verdict.lineage_chain:
        if step.step == 1:
            label = f"[!] {step.entity_name}"
        elif step.entity_type == "author":
            label = f"[author] {step.entity_name}"
        else:
            label = step.entity_name
        if (step.metadata or {}).get("data_source") == "representative":
            label += " (rep)"
        lines.append(f'  N{step.step}["{label}"]')

    for i in range(len(verdict.lineage_chain) - 1):
        lines.append(f"  N{i+1} --> N{i+2}")

    return "\n".join(lines)


def format_verdict_as_markdown(verdict: ProvenanceVerdict) -> str:
    """Format the verdict as GitLab markdown for posting to MR."""
    md = f"""## Vulnerability Analysis

### Finding
- **ID:** {verdict.finding_id}
- **Title:** {verdict.finding_title}
- **Severity:** {verdict.severity} (CVSS {verdict.cvss_score})

### Lineage
```mermaid
{format_verdict_as_mermaid_graph(verdict)}
```

### Key Details
- **Affected Symbol:** `{verdict.affected_symbol}`
- **Introducing MR:** {verdict.introducing_mr_id}
- **Introducing Author:** {verdict.introducing_author}

### Exposure Scope
Reachable in {len(verdict.exposure_scope)} services:
"""

    if verdict.composed_from_impact:
        md += f"> _Composed: {verdict.composition_note}_\n\n"

    for svc in verdict.exposure_scope:
        deployed = " [OK] deployed" if svc.is_deployed else " [!] not deployed"
        md += f"- **{svc.project_name}** ({deployed})\n"

    if verdict.critical_path:
        md += "\n [!] **CRITICAL PATH** — This service is in a critical path (payments, auth, etc.)\n"

    md += f"""
### Remediation
- **Recommended Fix:** Replace `yaml.load()` with `yaml.safe_load()` in `{verdict.affected_symbol}`
- **Estimated Effort:** 1-2 hours (code + tests + review)
- **Risk:** LOW (safe_load is drop-in replacement)
- **Work Item:** {verdict.remediation_work_item_id or "Auto-created, pending assignment"}

### Confidence: {verdict.confidence:.0%}
"""

    return md


if __name__ == "__main__":
    # Quick test
    finding_event = {
        "finding_id": "cve-2026-1234",
        "title": "RCE in yaml.load()",
        "severity": "CRITICAL",
        "cvss_score": 9.1,
        "affected_symbol": "process_config",
    }

    agent = ProvenanceAgent(orbit_client=None)
    verdict = agent.analyze_finding(finding_event)

    print(json.dumps(asdict(verdict), indent=2, default=str))
    print("\n" + format_verdict_as_markdown(verdict))
