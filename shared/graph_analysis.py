#!/usr/bin/env python3
"""
Graph analysis: structural chokepoints (cut vertices) over a call subgraph.

This is real graph reasoning, distinct from inbound-call counting. A keystone
is "called by many things" (high fan-in). A CHOKEPOINT is a cut vertex
(articulation point): a definition whose removal disconnects part of the
dependency graph, isolating downstream code from the rest. A symbol can have a
huge fan-in yet NOT be a chokepoint (its callers reach the graph by other
paths), and a modest-fan-in symbol can be a severe chokepoint. The two
measures answer different questions, so we compute both.

Implementation: on the undirected induced subgraph, a node is a cut vertex iff
removing it increases the number of connected components. For each cut vertex we
also report `isolated` = how many definitions get severed from the largest
remaining component if that node fails. The subgraph is small (hundreds of
nodes locally), so a clear remove-and-recount approach is used; it is bounded by
`max_nodes` to stay safe on larger graphs.
"""

from typing import Dict, List, Set, Tuple, Any


def _build_undirected(edges: List[Tuple[str, str]]) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = {}
    for s, t in edges:
        if s == t:
            continue
        adj.setdefault(s, set()).add(t)
        adj.setdefault(t, set()).add(s)
    return adj


def _count_components(adj: Dict[str, Set[str]], exclude: str = None) -> List[int]:
    """Return the sizes of connected components, optionally excluding one node."""
    seen: Set[str] = set()
    if exclude is not None:
        seen.add(exclude)
    sizes: List[int] = []
    for start in adj:
        if start in seen:
            continue
        # iterative DFS
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            u = stack.pop()
            size += 1
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        sizes.append(size)
    return sizes


def find_chokepoints(
    edges: List[Tuple[str, str]],
    roots: List[str] = None,
    max_nodes: int = 8000,
) -> List[Dict[str, Any]]:
    """
    Find cut vertices in the induced subgraph and rank them by isolation impact.

    Returns a list of dicts: {node, isolated, components_created, is_root},
    sorted by `isolated` descending. Returns [] if the graph is empty or larger
    than max_nodes (we log-and-skip rather than block on a huge graph).
    """
    roots = set(roots or [])
    adj = _build_undirected(edges)
    nodes = list(adj.keys())
    if not nodes or len(nodes) > max_nodes:
        return []

    base_components = len(_count_components(adj))
    total = len(nodes)

    results: List[Dict[str, Any]] = []
    for node in nodes:
        sizes = _count_components(adj, exclude=node)
        if len(sizes) > base_components:
            # node is a cut vertex: removing it created new components
            largest = max(sizes) if sizes else 0
            isolated = (total - 1) - largest  # nodes severed from the main body
            results.append({
                "node": node,
                "isolated": isolated,
                "components_created": len(sizes) - base_components,
                "is_root": node in roots,
            })

    results.sort(key=lambda r: (r["isolated"], r["components_created"]), reverse=True)
    return results


def pagerank(
    edges: List[Tuple[str, str]],
    damping: float = 0.85,
    iterations: int = 60,
    tol: float = 1e-9,
) -> Dict[str, float]:
    """
    PageRank over a directed call graph. Rank flows from a node to the nodes it
    points to: with edges (caller -> callee), a definition called by important
    code accrues importance. This is true eigenvector-style centrality, not a
    raw inbound-call count — a callee of a few very-central callers can outrank
    a callee of many trivial ones.

    Dangling nodes (no out-edges) redistribute their mass uniformly so the
    total rank is conserved. Converges in a few dozen iterations on this scale.
    """
    out: Dict[str, List[str]] = {}
    nodes: Set[str] = set()
    for s, t in edges:
        out.setdefault(s, []).append(t)
        nodes.add(s)
        nodes.add(t)

    n = len(nodes)
    if n == 0:
        return {}

    rank = {node: 1.0 / n for node in nodes}
    dangling = [node for node in nodes if not out.get(node)]

    for _ in range(iterations):
        base = (1.0 - damping) / n
        dangling_mass = damping * sum(rank[d] for d in dangling) / n
        new = {node: base + dangling_mass for node in nodes}
        for s, dsts in out.items():
            share = damping * rank[s] / len(dsts)
            for t in dsts:
                new[t] += share
        diff = sum(abs(new[node] - rank[node]) for node in nodes)
        rank = new
        if diff < tol:
            break
    return rank


def rank_map(scores: Dict[str, float]) -> Dict[str, int]:
    """Turn {node: score} into {node: 1-based rank} (highest score = rank 1)."""
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return {node: i + 1 for i, (node, _) in enumerate(ordered)}


if __name__ == "__main__":
    # Tiny sanity check: a path a-b-c-d -> b and c are cut vertices.
    e = [("a", "b"), ("b", "c"), ("c", "d")]
    for cp in find_chokepoints(e):
        print(cp)
    # PageRank: d (sink reached through the chain) should rank highest.
    pr = pagerank(e)
    print("pagerank:", sorted(pr.items(), key=lambda kv: -kv[1]))
