#!/usr/bin/env python3
"""
Git-truth ownership: who really owns the blast radius, from git blame.

Constellation's structural Ownership lens groups impact by code AREA and openly
hedges "CODEOWNERS pending at deploy." This closes that gap with zero new data
sources: for the changed symbols and their transitive-caller blast radius, it
runs `git blame` over each definition's exact line span, attributes the surviving
lines to real authors, and WEIGHTS each definition by its call-graph centrality
(inbound calls). The result is a real bus-factor, a "reviewers who actually know
this code" list, and a single-point-of-failure warning - grounded in commits, not
file-path proxies.

Privacy: git blame on a real repo yields real people. By DEFAULT this module
ANONYMIZES authors to stable ordinal labels ("Author A", ranked by ownership),
so a public hackathon verdict never names an individual as a SPOF. Set
CONSTELLATION_REAL_NAMES=1 to reveal real names/emails for internal use.

    BACKTEST_ORBIT=/path/to/orbit SCAR_REPO=/path/to/repo python ci/git_ownership.py

Wired into CI via run_ci.py -> payload['git_ownership']; absent-safe (when not
supplied, the structural Ownership lens is unchanged).
"""

import math
import os
import subprocess
import sys
from typing import Dict, List, Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))
from orbit_real_client import RealOrbitClient   # noqa: E402

MAX_BLAME_DEFS = 40       # cap git-blame calls (one per definition span)
SPOF_SHARE = 0.70         # one author owning >= this share of a def = SPOF flag
REAL_NAMES = os.environ.get("CONSTELLATION_REAL_NAMES") == "1"


def _centrality_weight(inbound: int) -> float:
    """
    Sublinear (diminishing-returns) weight so a load-bearing definition counts
    for more than a leaf, but a single mega-keystone cannot swamp the whole
    distribution into a degenerate one-author result. A leaf (0 callers) weighs
    1.0; a 176-caller keystone weighs ~6.2, not 50x a leaf.
    """
    return 1.0 + math.log1p(max(inbound, 0))


def _git(repo: str, *args: str):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, errors="replace"
    )


def _blast_definitions(client, symbols: List[str]) -> List[Dict[str, Any]]:
    """
    The changed symbols + their top transitive callers, each as a real
    definition with file/line span and inbound-call count (the weight).

    This is the per-definition view the structural lens lacks: _query_affected_files
    aggregates by file, so the line spans needed for blame are recovered here.
    """
    qs = RealOrbitClient._quote_symbols(symbols)
    seed_sql = f"""
SELECT d.id, d.name, d.file_path, d.start_line, d.end_line,
       COUNT(DISTINCT e.source_id) AS inbound
FROM gl_definition d
LEFT JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
WHERE d.name IN ({qs})
GROUP BY d.id, d.name, d.file_path, d.start_line, d.end_line;
"""
    caller_sql = client._recursive_callers_cte(symbols) + f"""
SELECT d.id, d.name, d.file_path, d.start_line, d.end_line,
       COUNT(DISTINCT e.source_id) AS inbound
FROM callers c
JOIN gl_definition d ON d.id = c.id
LEFT JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
GROUP BY d.id, d.name, d.file_path, d.start_line, d.end_line
ORDER BY inbound DESC
LIMIT {MAX_BLAME_DEFS};
"""
    seen, defs = set(), []
    for r in (client.query_raw(seed_sql) + client.query_raw(caller_sql)):
        did = r.get("id")
        if did in seen:
            continue
        seen.add(did)
        from orbit_real_client import _to_int
        sl, el = _to_int(r.get("start_line")), _to_int(r.get("end_line"))
        if sl < 1 or el < sl:
            continue
        defs.append({
            "id": did, "name": r.get("name"),
            "file_path": (r.get("file_path") or "").replace("\\", "/"),
            "start_line": sl, "end_line": el,
            "weight": _centrality_weight(_to_int(r.get("inbound"))),
            "inbound": _to_int(r.get("inbound")),
        })
    # Blame the highest-weight definitions first (most load-bearing).
    defs.sort(key=lambda d: -d["weight"])
    return defs[:MAX_BLAME_DEFS]


def _blame_lines(repo: str, file_path: str, lo: int, hi: int) -> Dict[str, Dict[str, Any]]:
    """{identity: {name, email, lines}} for surviving lines in [lo, hi]."""
    # Plain blame (last meaningful author per line). We deliberately omit -C
    # (cross-file copy detection): it can attribute copied code to an unrelated
    # original author - the over-attribution the project's no-overclaim brand
    # avoids. -w ignores whitespace-only reformats.
    res = _git(repo, "blame", "-w", "--line-porcelain",
               "-L", f"{lo},{hi}", "--", file_path)
    if res.returncode != 0 or not res.stdout:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    name = email = None
    for line in res.stdout.split("\n"):
        if line.startswith("author "):
            name = line[7:].strip()
        elif line.startswith("author-mail "):
            email = line[12:].strip().strip("<>").lower()
        elif line.startswith("\t"):                      # an actual source line
            ident = email or name or "unknown"
            rec = out.setdefault(ident, {"name": name or ident, "email": email or "", "lines": 0})
            rec["lines"] += 1
    return out


def compute_git_ownership(client, symbols: List[str], repo: str = ".") -> Dict[str, Any]:
    """Real, centrality-weighted authorship over the blast radius (anonymized)."""
    if not symbols:
        return {"available": False}

    defs = _blast_definitions(client, symbols)
    mass: Dict[str, float] = {}          # identity -> weighted ownership mass
    identname: Dict[str, str] = {}       # identity -> real display name
    per_def = []                         # for the SPOF example
    blamed = 0

    for d in defs:
        lines = _blame_lines(repo, d["file_path"], d["start_line"], d["end_line"])
        if not lines:
            continue
        blamed += 1
        total = sum(v["lines"] for v in lines.values()) or 1
        top_ident, top_rec = max(lines.items(), key=lambda kv: kv[1]["lines"])
        per_def.append({
            "name": d["name"], "file": d["file_path"], "inbound": d["inbound"],
            "weight": d["weight"], "dom_ident": top_ident,
            "dom_share": top_rec["lines"] / total,
        })
        for ident, v in lines.items():
            mass[ident] = mass.get(ident, 0.0) + v["lines"] * d["weight"]
            identname.setdefault(ident, v["name"])

    total_mass = sum(mass.values())
    if total_mass <= 0:
        return {"available": False, "definitions_blamed": 0}

    ranked = sorted(mass.items(), key=lambda kv: -kv[1])
    # Stable anonymized labels by ownership rank.
    label = {ident: f"Author {chr(ord('A') + i)}" for i, (ident, _) in enumerate(ranked)}

    def display(ident):
        if REAL_NAMES:
            nm = identname.get(ident, ident)
            return f"{nm} <{ident}>" if "@" in ident else nm
        return label.get(ident, "Author ?")

    owners = []
    cum = 0.0
    bus_factor = 0
    for ident, m in ranked:
        share = m / total_mass
        cum += share
        if bus_factor == 0 and cum > 0.50:
            bus_factor = len(owners) + 1
        owners.append({"owner": display(ident), "share": round(share, 3),
                       "weighted_mass": round(m, 1)})
    bus_factor = bus_factor or len(owners)
    concentration = owners[0]["share"] if owners else 0.0

    # SPOF: the highest-centrality definition a single author dominates.
    spof_candidates = [p for p in per_def if p["dom_share"] >= SPOF_SHARE]
    spof_candidates.sort(key=lambda p: (-p["inbound"], -p["dom_share"]))
    spof = None
    if spof_candidates or bus_factor <= 1:
        if spof_candidates:
            p = spof_candidates[0]
            spof = {
                "is_spof": True, "owner": display(p["dom_ident"]),
                "symbol": p["name"], "file": p["file"], "inbound": p["inbound"],
                "share": round(p["dom_share"], 2),
                "note": (f"{display(p['dom_ident'])} wrote {p['dom_share']:.0%} of "
                         f"`{p['name']}` ({p['inbound']} callers) - if they are "
                         f"unavailable, no one else knows this load-bearing code well."),
            }
        else:
            spof = {
                "is_spof": True, "owner": owners[0]["owner"],
                "share": round(concentration, 2),
                "note": (f"{owners[0]['owner']} owns {concentration:.0%} of the impacted "
                         f"load-bearing code - bus factor 1."),
            }

    return {
        "available": True,
        "anonymized": not REAL_NAMES,
        "definitions_blamed": blamed,
        "bus_factor": bus_factor,
        "concentration": round(concentration, 3),
        "owners": owners[:6],
        "reviewers": [o["owner"] for o in owners[:4]],
        "spof": spof,
        "note": ("real authorship from git blame over the blast radius, weighted by "
                 "call centrality" + ("; anonymized" if not REAL_NAMES else "")),
    }


def _main() -> int:
    repo = os.environ.get("SCAR_REPO", ".")
    client = RealOrbitClient(orbit_binary_path=os.environ.get("BACKTEST_ORBIT", "orbit"))
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2
    symbols = sys.argv[1:] or ["compile"]
    res = compute_git_ownership(client, symbols, repo=repo)
    print("=" * 78)
    print(f"CONSTELLATION - git-truth ownership of the blast radius of {symbols}")
    print("=" * 78)
    if not res.get("available"):
        print("\n(no blame data resolved - spans may not align with HEAD)")
        return 0
    print(f"\nDefinitions blamed: {res['definitions_blamed']}  |  "
          f"bus factor: {res['bus_factor']}  |  top owner: {res['concentration']:.0%}")
    print(f"Anonymized: {res['anonymized']}  (set CONSTELLATION_REAL_NAMES=1 to reveal)\n")
    print("Real owners of the impacted code (centrality-weighted):")
    for o in res["owners"]:
        print(f"  {o['owner']:12}  {o['share']:.0%}")
    if res.get("spof"):
        print("\n" + "-" * 78)
        print("Single point of failure:")
        print("  " + res["spof"]["note"])
    return 0


if __name__ == "__main__":
    sys.exit(_main())
