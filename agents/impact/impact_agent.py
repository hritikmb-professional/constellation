#!/usr/bin/env python3
"""
Impact Agent: Compute true change blast radius over GitLab Orbit.

Input: MR event with changed symbols
Output: Transitive dependents + affected owners + change-failure prediction
"""

import json
import sys
import os
from typing import Dict, List, Any
from dataclasses import dataclass, asdict, field
import logging

# Make shared/ importable for direct runs (callers also add it to sys.path).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared"))
try:
    from graph_analysis import find_chokepoints, pagerank, rank_map
except ImportError:
    find_chokepoints = None
    pagerank = None
    rank_map = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AffectedService:
    """A service affected by the blast radius."""
    project_id: str
    project_name: str
    full_path: str
    affected_definitions: int
    is_critical_path: bool = False


@dataclass
class AffectedOwner:
    """A code owner affected by the change."""
    user_id: str
    username: str
    name: str
    affected_definitions: int
    services_touched: int


@dataclass
class KeystoneSymbol:
    """A changed symbol that is a high-fan-in single point of failure.

    `centrality_rank` is the caller-count rank (rank by inbound calls).
    `pagerank_rank` is the REAL eigenvector centrality rank (PageRank over the
    whole call graph); 0 means not computed. The two can disagree: a symbol can
    be the most-called in scope yet sit mid-pack in global PageRank.
    """
    name: str
    inbound_calls: int
    centrality_rank: int
    pagerank_rank: int = 0


@dataclass
class Chokepoint:
    """
    A structural cut vertex in the blast-radius subgraph: a definition whose
    failure disconnects part of the dependency graph. Distinct from a keystone
    (high fan-in) — this measures topological criticality, not call count.
    """
    name: str
    file: str
    isolated: int        # definitions severed from the main body if this fails
    is_changed: bool     # whether this is one of the changed symbols in the MR


@dataclass
class BlastRadiusVerdict:
    """The verdict from the Impact agent."""
    event_id: str
    changed_symbols: List[str]
    total_dependents: int
    affected_services: List[AffectedService]
    affected_owners: List[AffectedOwner]
    change_failure_rate: float
    confidence: float
    confidence_reasons: List[str]
    keystone_symbols: List[KeystoneSymbol] = field(default_factory=list)
    chokepoints: List[Chokepoint] = field(default_factory=list)
    test_dependents: int = 0          # dependents in test files (by path)
    production_dependents: int = 0     # dependents in production files


@dataclass
class MaterializedSubgraph:
    """
    The blast-radius subgraph Impact materializes ONCE and shares with
    downstream agents.

    This is the composition primitive of Constellation: every other lens
    (Provenance, Compliance, Ownership) consumes this object instead of
    re-traversing Orbit. The forward-reachability set computed here IS the
    exposure set a vulnerability inherits, the boundary Compliance checks,
    and the surface Ownership scores.
    """
    root_symbols: List[str]
    total_dependents: int
    affected_services: List[AffectedService]
    affected_owners: List[AffectedOwner]
    keystone_symbols: List[KeystoneSymbol]

    def covers_symbol(self, symbol: str) -> bool:
        """True if `symbol` is a root of this materialized subgraph."""
        return symbol in self.root_symbols


class ImpactAgent:
    """
    Impact Agent: Compute blast radius for a merge request.

    Implements the Impact lens: given a set of changed symbols,
    find all transitive dependents, affected services, owners, and
    predict change-failure risk.
    """

    def __init__(self, orbit_client):
        """Initialize with an Orbit client."""
        self.orbit_client = orbit_client
        # The most recent subgraph this agent materialized. Downstream agents
        # consume this instead of re-querying Orbit (shared-context composition).
        self.last_subgraph: "MaterializedSubgraph" = None
        # Cached PageRank rank map (computed once per agent, on first need).
        self._pagerank_ranks = None
        # (test_dependents, production_dependents) from the last services query.
        self._last_split = (0, 0)

    def analyze_mr(self, mr_event: Dict[str, Any]) -> BlastRadiusVerdict:
        """
        Analyze a merge request and compute its blast radius.

        Args:
            mr_event: MR event from GitLab webhook, including:
                - mr_id: internal MR ID
                - changed_files: list of changed file paths
                - changed_symbols: list of changed function/class names (if pre-computed)

        Returns:
            BlastRadiusVerdict with blast radius analysis.
        """
        mr_id = mr_event.get("mr_id")
        changed_symbols = mr_event.get("changed_symbols", [])

        logger.info(f"Impact: analyzing MR {mr_id}, {len(changed_symbols)} changed symbols")

        if not changed_symbols:
            logger.warning("No changed symbols provided; extracting from diff")
            changed_symbols = self._extract_symbols_from_diff(mr_event)

        # Query 1: Get transitive dependents
        dependents = self._query_transitive_dependents(changed_symbols)
        logger.info(f"Impact: found {dependents['total_dependents']} transitive dependents")

        # Query 2: Map to services
        affected_services = self._query_affected_services(changed_symbols)
        logger.info(f"Impact: changes affect {len(affected_services)} services")

        # Query 3: Map to owners
        affected_owners = self._query_affected_owners(changed_symbols)
        logger.info(f"Impact: changes affect {len(affected_owners)} owners")

        # Query 4: Detect keystone symbols (high fan-in single points of failure)
        keystones = self._detect_keystones(changed_symbols)
        if keystones:
            logger.info(f"Impact: {len(keystones)} keystone symbols touched (SPOF risk)")

        # Query 4b: Detect structural chokepoints (cut vertices) in the subgraph
        chokepoints = self._detect_chokepoints(changed_symbols)
        if chokepoints:
            logger.info(f"Impact: {len(chokepoints)} structural chokepoints in blast radius")

        # Query 5: Predict change-failure rate (structural, real-signal heuristic)
        failure_rate = self._predict_change_failure_rate(
            affected_services,
            changed_symbols,
            keystones,
            total_dependents=dependents.get("total_dependents", 0),
            chokepoints=chokepoints,
        )
        logger.info(f"Impact: predicted failure rate = {failure_rate:.2f}")

        # Compute confidence
        confidence, reasons = self._compute_confidence(mr_event, dependents, affected_services)

        verdict = BlastRadiusVerdict(
            event_id=mr_id,
            changed_symbols=changed_symbols,
            total_dependents=dependents["total_dependents"],
            affected_services=affected_services,
            affected_owners=affected_owners,
            change_failure_rate=failure_rate,
            confidence=confidence,
            confidence_reasons=reasons,
            keystone_symbols=keystones,
            chokepoints=chokepoints,
            test_dependents=self._last_split[0],
            production_dependents=self._last_split[1],
        )

        # Materialize the subgraph once so downstream lenses can consume it
        # instead of re-traversing Orbit.
        self.last_subgraph = MaterializedSubgraph(
            root_symbols=changed_symbols,
            total_dependents=dependents["total_dependents"],
            affected_services=affected_services,
            affected_owners=affected_owners,
            keystone_symbols=keystones,
        )

        return verdict

    def _detect_keystones(self, changed_symbols: List[str]) -> List[KeystoneSymbol]:
        """
        Flag changed symbols that are high-centrality single points of failure.

        A keystone is a symbol whose inbound call count places it in the
        top tier of the codebase. Changing one is disproportionately risky.
        Uses the ownership_centrality query already supported by the client.
        """
        if not changed_symbols or not self.orbit_client:
            return []

        try:
            result = self.orbit_client.query("ownership_centrality")
        except Exception as e:
            logger.warning(f"Impact: centrality query failed ({e}); skipping keystone check")
            return []

        ranked = result.get("high_centrality", []) if result else []
        changed_set = {s.lower() for s in changed_symbols}

        # Keep only the highest-centrality (first-seen) occurrence per name:
        # the same symbol name can appear as several definitions.
        keystones: List[KeystoneSymbol] = []
        seen = set()
        for rank, entry in enumerate(ranked, start=1):
            name = (entry.get("name") or "").strip()
            key = name.lower()
            if key in changed_set and key not in seen:
                seen.add(key)
                keystones.append(
                    KeystoneSymbol(
                        name=name,
                        inbound_calls=int(entry.get("inbound", 0)),
                        centrality_rank=rank,
                    )
                )
        # Annotate with REAL PageRank centrality (only when there are keystones).
        return self._attach_pagerank(keystones)

    def _get_pagerank_ranks(self) -> Dict[str, int]:
        """Compute (once) the global PageRank rank map over the whole call graph."""
        if self._pagerank_ranks is not None:
            return self._pagerank_ranks
        self._pagerank_ranks = {}
        if not self.orbit_client or pagerank is None:
            return self._pagerank_ranks
        try:
            edges = self.orbit_client.query("all_call_edges").get("edges", [])
        except Exception as e:
            logger.warning(f"Impact: call-edge fetch failed ({e}); skipping PageRank")
            return self._pagerank_ranks
        if edges:
            self._pagerank_ranks = rank_map(pagerank(edges))
        return self._pagerank_ranks

    def _attach_pagerank(self, keystones: List[KeystoneSymbol]) -> List[KeystoneSymbol]:
        """Attach the real PageRank centrality rank to each keystone symbol."""
        if not keystones:
            return keystones
        ranks = self._get_pagerank_ranks()
        if not ranks:
            return keystones
        try:
            defs = self.orbit_client.query(
                "symbol_defs", symbols=[k.name for k in keystones]
            ).get("defs", [])
        except Exception:
            return keystones
        # Best (lowest) PageRank rank per symbol name.
        best: Dict[str, int] = {}
        for d in defs:
            r = ranks.get(d.get("id"))
            if r is None:
                continue
            nm = d.get("name")
            if nm not in best or r < best[nm]:
                best[nm] = r
        for k in keystones:
            k.pagerank_rank = best.get(k.name, 0)
        return keystones

    def _detect_chokepoints(self, changed_symbols: List[str], top_n: int = 5) -> List[Chokepoint]:
        """
        Find cut vertices (articulation points) in the blast-radius subgraph.

        A chokepoint is a definition whose removal disconnects part of the
        dependency graph. This is real topological criticality, distinct from a
        keystone's fan-in count: a symbol can be called by hundreds of things
        yet not be a chokepoint, and vice versa.
        """
        if not changed_symbols or not self.orbit_client or find_chokepoints is None:
            return []

        try:
            sg = self.orbit_client.query("subgraph_edges", symbols=changed_symbols)
        except Exception as e:
            logger.warning(f"Impact: subgraph-edge query failed ({e}); skipping chokepoints")
            return []

        edges = sg.get("edges", []) if sg else []
        roots = sg.get("roots", []) if sg else []
        if not edges:
            return []

        ranked = [c for c in find_chokepoints(edges, roots=roots) if c["isolated"] > 0]
        if not ranked:
            return []

        # Resolve a generous candidate set so we can dedup by name and still
        # return the top distinct chokepoints. (sorted by isolation already.)
        candidates = ranked[: top_n * 4]
        ids = [c["node"] for c in candidates]
        try:
            names = self.orbit_client.query("definitions_by_id", ids=ids).get("definitions", {})
        except Exception:
            names = {}

        root_set = set(roots)
        chokepoints: List[Chokepoint] = []
        seen_names: set = set()
        for c in candidates:
            info = names.get(c["node"], {})
            name = info.get("name")
            # Skip graph nodes with no gl_definition row (imported/external
            # symbols) — a chokepoint must be a named definition, never a raw id.
            if not name:
                continue
            # Same name can appear as several definitions; keep the highest-impact.
            if name in seen_names:
                continue
            seen_names.add(name)
            chokepoints.append(
                Chokepoint(
                    name=name,
                    file=info.get("file_path") or "",
                    isolated=int(c["isolated"]),
                    is_changed=c["node"] in root_set,
                )
            )
            if len(chokepoints) >= top_n:
                break
        return chokepoints

    def _extract_symbols_from_diff(self, mr_event: Dict[str, Any]) -> List[str]:
        """
        Extract function/class symbols from the MR diff.

        For now, returns empty list. In production, would parse diff
        and use regex/AST to identify changed definitions.
        """
        logger.warning("Symbol extraction not yet implemented; returning empty list")
        return []

    def _query_transitive_dependents(self, changed_symbols: List[str]) -> Dict[str, Any]:
        """
        Query Orbit for transitive dependents of changed symbols.

        Uses shared/queries.sql Query 1b.
        """
        if not changed_symbols:
            return {"total_dependents": 0, "affected_services": 0, "max_depth": 0}

        logger.info(f"Impact: querying transitive dependents of {changed_symbols}")

        # Query Orbit for real results
        if self.orbit_client:
            result = self.orbit_client.query("transitive_dependents", symbols=changed_symbols)
            if result:
                return result

        # Fallback to mock if no client
        return {
            "total_dependents": 14,
            "affected_services": 3,
            "service_ids": ["api-svc", "data-svc", "worker-svc"],
            "max_depth": 4,
            "median_depth": 2,
        }

    def _query_affected_services(self, changed_symbols: List[str]) -> List[AffectedService]:
        """Query Orbit for affected services (file/module-level blast radius)."""
        logger.info(f"Impact: querying affected services")

        if self.orbit_client and changed_symbols:
            result = self.orbit_client.query("affected_services", symbols=changed_symbols)
            items = result.get("affected_services", []) if result else []
            # Capture the test/production split (computed over ALL affected files).
            self._last_split = (
                int(result.get("test_dependents", 0)),
                int(result.get("production_dependents", 0)),
            )
            services = [
                AffectedService(
                    project_id=str(it.get("project_id", "")),
                    project_name=it.get("project_name", ""),
                    full_path=it.get("full_path", ""),
                    affected_definitions=int(it.get("affected_definitions", 0)),
                    is_critical_path=bool(it.get("is_critical_path", False)),
                )
                for it in items
            ]
            # Trust the client's result (including empty) when a client exists.
            return services[:6]

        # Fallback only when there is no client at all (standalone runs).
        return [
            AffectedService("p1", "api-service", "microservices/api-service", 6, True),
            AffectedService("p2", "data-service", "microservices/data-service", 5, False),
            AffectedService("p3", "worker-service", "microservices/worker-service", 3, False),
        ]

    def _query_affected_owners(self, changed_symbols: List[str]) -> List[AffectedOwner]:
        """Query Orbit for owners of affected code (structural code areas)."""
        logger.info(f"Impact: querying affected owners")

        if self.orbit_client and changed_symbols:
            result = self.orbit_client.query("affected_owners", symbols=changed_symbols)
            items = result.get("affected_owners", []) if result else []
            owners = [
                AffectedOwner(
                    user_id=str(it.get("user_id", "")),
                    username=it.get("username", ""),
                    name=it.get("name", ""),
                    affected_definitions=int(it.get("affected_definitions", 0)),
                    services_touched=int(it.get("services_touched", 0)),
                )
                for it in items
            ]
            return owners[:5]

        # Fallback only when there is no client at all (standalone runs).
        return [
            AffectedOwner("u1", "alice", "Alice Chen", 8, 2),
            AffectedOwner("u2", "bob", "Bob Smith", 6, 2),
        ]

    def _predict_change_failure_rate(
        self,
        affected_services: List[AffectedService],
        changed_symbols: List[str],
        keystones: List[KeystoneSymbol] = None,
        total_dependents: int = 0,
        chokepoints: List["Chokepoint"] = None,
    ) -> float:
        """
        Estimate change-failure rate as a transparent STRUCTURAL HEURISTIC
        (not a learned or historical model). It is a weighted sum of real
        signals from this change, each clearly attributable:

            base                         0.05
          + keystone exposure            0.06 per keystone (capped at 0.18)
          + blast-radius magnitude       0.15 (>=300) / 0.10 (>=100) / 0.05 (>=25)
          + structural chokepoint        0.08 if a CHANGED symbol is a cut vertex
          + critical-path file touched   0.05

        Every term maps to a concrete, inspectable property of the change, so
        the number is defensible and reproducible — not an opaque constant.
        """
        logger.info("Impact: predicting change-failure rate")
        keystones = keystones or []
        chokepoints = chokepoints or []

        score = 0.05
        score += min(0.18, 0.06 * len(keystones))

        if total_dependents >= 300:
            score += 0.15
        elif total_dependents >= 100:
            score += 0.10
        elif total_dependents >= 25:
            score += 0.05

        if any(getattr(c, "is_changed", False) for c in chokepoints):
            score += 0.08

        if any(s.is_critical_path for s in affected_services):
            score += 0.05

        return min(score, 0.90)

    def _compute_confidence(
        self, mr_event: Dict[str, Any], dependents: Dict, affected_services: List[AffectedService]
    ) -> tuple[float, List[str]]:
        """
        Compute confidence score and reasons.

        Confidence starts high on a fully-resolved local graph and is reduced by
        real signals of incompleteness: unavailable (private) repos in the blast
        radius, and generated code among the affected files (stale references).
        """
        confidence = 0.95
        reasons = []

        # Private/unavailable repos in the blast radius reduce closure certainty.
        private_count = sum(1 for s in affected_services if "private" in s.full_path.lower())
        if private_count > 0:
            confidence -= 0.05 * private_count
            reasons.append(f"{private_count} private repos unavailable")

        # Generated code among affected files implies possibly-stale references.
        generated_count = sum(
            1 for s in affected_services
            if "generated" in s.full_path.lower() or "/gen/" in s.full_path.lower()
        )
        if generated_count > 0:
            confidence -= 0.1
            reasons.append(f"{generated_count} generated-code files in scope")

        return max(0.0, confidence), reasons


def format_verdict_as_markdown(verdict: BlastRadiusVerdict) -> str:
    """Format the verdict as GitLab markdown for posting to MR."""
    md = f"""## Impact Analysis

**Blast Radius:** {verdict.total_dependents} transitive dependents across {len(verdict.affected_services)} services

"""

    for svc in verdict.affected_services:
        critical = " (critical path)" if svc.is_critical_path else ""
        label = svc.full_path or svc.project_name
        md += f"- `{label}` ({svc.affected_definitions} affected){critical}\n"

    if verdict.keystone_symbols:
        md += "\n**[!] Keystone Symbols (high fan-in single points of failure):**\n"
        for k in verdict.keystone_symbols:
            pr = f"; PageRank centrality #{k.pagerank_rank}" if k.pagerank_rank else ""
            md += f"- `{k.name}` - {k.inbound_calls} inbound callers (caller-count #{k.centrality_rank}{pr})\n"

    if verdict.chokepoints:
        md += "\n**[!] Chokepoints (cut vertices - failure isolates downstream code):**\n"
        for c in verdict.chokepoints:
            tag = " (changed by this MR)" if c.is_changed else ""
            md += f"- `{c.name}` isolates {c.isolated} definitions if it fails{tag}\n"

    md += f"""
**Affected Owners:** {", ".join(o.username for o in verdict.affected_owners)}

**Change-Failure Risk:** {verdict.change_failure_rate:.0%}
(Heuristic: base rate escalated per keystone touched; not a historical model)

**Confidence:** {verdict.confidence:.0%}
"""
    if verdict.confidence_reasons:
        md += "Reasons: " + "; ".join(verdict.confidence_reasons) + "\n"

    return md


if __name__ == "__main__":
    # Quick test
    mr_event = {
        "mr_id": "mr-123",
        "changed_symbols": ["process_config", "validate_input"],
    }

    agent = ImpactAgent(orbit_client=None)
    verdict = agent.analyze_mr(mr_event)

    print(json.dumps(asdict(verdict), indent=2, default=str))
    print("\n" + format_verdict_as_markdown(verdict))
