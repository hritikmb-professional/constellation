#!/usr/bin/env python3
"""
Ownership Agent: Measure bus-factor / ownership-concentration risk.

This is a thin, real lens that is deliberately DISTINCT from Impact. Impact
answers "how much breaks?" (blast size). Ownership answers "who carries it,
and what happens if that area's maintainer leaves?" (concentration /
single-point-of-failure of areas, not just code).

It is a composition consumer: it does NOT re-query Orbit. It reads the subgraph
Impact already materialized (affected owners + keystones) and scores ownership
risk over it.
"""

import sys
from typing import Dict, List, Any
from dataclasses import dataclass, asdict, field
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class OwningArea:
    """A code area carrying part of the blast radius."""
    name: str
    affected_definitions: int
    share: float  # fraction of the total affected definitions


@dataclass
class OwnershipVerdict:
    """The verdict from the Ownership lens."""
    event_id: str
    total_affected: int
    owning_areas: List[OwningArea]
    top_area: str
    concentration: float        # share owned by the single top area (0..1)
    bus_factor: int             # number of distinct owning areas
    keystones_in_radius: List[str]
    risk_level: str             # LOW, MEDIUM, HIGH
    risk_note: str
    composed_from_impact: bool = True
    owning_areas_source: str = "structural (CODEOWNERS enrichment pending at deploy)"
    confidence: float = 0.0


class OwnershipAgent:
    """
    Ownership lens: score concentration / bus-factor risk over Impact's
    materialized subgraph.
    """

    def analyze_subgraph(self, event_id: str, shared_subgraph) -> OwnershipVerdict:
        """
        Score ownership risk for a materialized blast-radius subgraph.

        Args:
            event_id: the originating event id.
            shared_subgraph: a MaterializedSubgraph from the Impact agent.
        """
        owners = list(shared_subgraph.affected_owners)
        keystones = [k.name for k in shared_subgraph.keystone_symbols]

        total_affected = sum(o.affected_definitions for o in owners) or 0
        logger.info(f"Ownership: scoring {len(owners)} areas over {total_affected} affected defs")

        owning_areas: List[OwningArea] = []
        for o in owners:
            share = (o.affected_definitions / total_affected) if total_affected else 0.0
            owning_areas.append(
                OwningArea(name=o.username, affected_definitions=o.affected_definitions, share=share)
            )

        top_area = owning_areas[0].name if owning_areas else "unknown"
        concentration = owning_areas[0].share if owning_areas else 0.0
        bus_factor = len(owning_areas)

        risk_level, risk_note = self._score_risk(concentration, bus_factor, keystones)
        confidence = 0.85 if owners else 0.0

        verdict = OwnershipVerdict(
            event_id=event_id,
            total_affected=total_affected,
            owning_areas=owning_areas,
            top_area=top_area,
            concentration=concentration,
            bus_factor=bus_factor,
            keystones_in_radius=keystones,
            risk_level=risk_level,
            risk_note=risk_note,
            confidence=confidence,
        )
        return verdict

    def _score_risk(self, concentration: float, bus_factor: int, keystones: List[str]):
        """
        Ownership risk is high when the blast radius is concentrated in one
        area (low bus factor) AND/OR sits on a keystone. A change spread evenly
        across many owned areas is safer than one funneled through a single
        area that one person maintains.
        """
        if bus_factor <= 1 or concentration >= 0.90:
            if keystones:
                return "HIGH", (
                    f"{concentration:.0%} of impact concentrated in one area which owns "
                    f"keystone(s) {', '.join(keystones)} - severe bus-factor risk."
                )
            return "HIGH", (
                f"{concentration:.0%} of impact concentrated in a single area - bus-factor risk."
            )
        if concentration >= 0.60 or keystones:
            return "MEDIUM", (
                f"Impact leans on '{keystones[0] if keystones else 'one area'}'; "
                "ownership is moderately concentrated."
            )
        return "LOW", "Impact is distributed across multiple owned areas."


def format_verdict_as_markdown(verdict: OwnershipVerdict) -> str:
    """Format the ownership verdict as GitLab markdown."""
    md = f"""## Ownership Risk

**Bus factor:** {verdict.bus_factor} owning area(s)
**Concentration:** {verdict.concentration:.0%} of impact in `{verdict.top_area}`
**Risk:** {verdict.risk_level} - {verdict.risk_note}

Owning areas (by affected definitions):
"""
    for area in verdict.owning_areas[:5]:
        md += f"- `{area.name}` - {area.affected_definitions} ({area.share:.0%})\n"

    md += f"\n_Ownership source: {verdict.owning_areas_source}_\n"
    md += f"_Composed from Impact's materialized subgraph; confidence {verdict.confidence:.0%}_\n"
    return md


if __name__ == "__main__":
    # Tiny smoke test with a stub subgraph.
    from dataclasses import dataclass as _dc

    @_dc
    class _Owner:
        username: str
        affected_definitions: int

    @_dc
    class _Keystone:
        name: str

    @_dc
    class _Subgraph:
        affected_owners: list
        keystone_symbols: list

    sub = _Subgraph(
        affected_owners=[_Owner("crates/integration-tests", 421), _Owner("crates/fuzz", 2)],
        keystone_symbols=[_Keystone("allow_all"), _Keystone("compile")],
    )
    v = OwnershipAgent().analyze_subgraph("mr-demo", sub)
    print(format_verdict_as_markdown(v))
