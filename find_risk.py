#!/usr/bin/env python3
"""
Find real latent fragility in the indexed codebase.

Surfaces PRODUCTION functions that are load-bearing (many production callers)
yet have NO test directly exercising them — a genuine "change-it-and-pray"
risk. Everything here is read straight from the Orbit graph and is verifiable.

    BACKTEST_ORBIT=/path/to/orbit.exe python find_risk.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared"))
from orbit_real_client import RealOrbitClient, _to_int   # noqa: E402

# SQL fragments for "is this a test file path" — kept in sync with
# RealOrbitClient._is_test_path.
_TEST_LIKE = (
    "(lower({col}) LIKE '%/tests/%' OR lower({col}) LIKE '%/test/%' "
    "OR lower({col}) LIKE '%integration-tests%' OR lower({col}) LIKE '%testkit%' "
    "OR lower({col}) LIKE '%testutil%' OR lower({col}) LIKE '%/spec%' "
    "OR lower({col}) LIKE '%/fixtures/%' OR lower({col}) LIKE '%/fuzz/%' "
    "OR lower({col}) LIKE '%/benches/%' OR lower({col}) LIKE '%/examples/%')"
)

# Machine-generated code — excluded (no tests expected).
_GEN_LIKE = (
    "(lower({col}) LIKE '%.pb.go' OR lower({col}) LIKE '%.pb.rs' "
    "OR lower({col}) LIKE '%_pb2.py' OR lower({col}) LIKE '%generated%' "
    "OR lower({col}) LIKE '%/gen/%' OR lower({col}) LIKE '%.gen.%')"
)


def main():
    orbit_bin = os.environ.get("BACKTEST_ORBIT", "orbit")
    client = RealOrbitClient(orbit_binary_path=orbit_bin)
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2

    caller_test = _TEST_LIKE.format(col="sd.file_path")
    target_test = _TEST_LIKE.format(col="d.file_path")
    target_gen = _GEN_LIKE.format(col="d.file_path")

    # Restrict to real functions (not types/structs/enums/accessors), in
    # production (not test, not generated) code.
    sql = f"""
SELECT d.name AS name, d.fqn AS fqn, d.file_path AS file_path,
       COUNT(DISTINCT e.source_id) AS total_callers,
       COUNT(DISTINCT CASE WHEN {caller_test} THEN e.source_id END) AS test_callers
FROM gl_definition d
JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
JOIN gl_definition sd ON sd.id = e.source_id
WHERE d.definition_type = 'Function'
  AND NOT {target_test}
  AND NOT {target_gen}
GROUP BY d.id, d.name, d.fqn, d.file_path
HAVING COUNT(DISTINCT e.source_id) >= 8
ORDER BY (COUNT(DISTINCT e.source_id) - COUNT(DISTINCT CASE WHEN {caller_test} THEN e.source_id END)) DESC
LIMIT 60;
"""
    rows = client.query_raw(sql)

    def _interesting(path):
        p = (path or "").lower()
        return any(k in p for k in (
            "auth", "security", "redaction", "compiler", "code-graph",
            "indexer", "pipeline", "billing", "config", "evaluat"))

    fragile = []
    for r in rows:
        total = _to_int(r.get("total_callers"))
        test = _to_int(r.get("test_callers"))
        prod = total - test
        if prod >= 8 and test == 0:        # load-bearing in prod, ZERO test coverage
            fragile.append((r.get("name"), r.get("fqn"), r.get("file_path"), prod, test))

    # Rank the "sharpest" by (in a security/core path, then fan-in) so the
    # headline is a meaningful function, not a thin observability wrapper.
    fragile.sort(key=lambda f: (_interesting(f[2]), f[3]), reverse=True)

    print("=" * 78)
    print("CONSTELLATION — latent fragility scan (production code, real Orbit graph)")
    print("=" * 78)
    print("\nReal functions, in production (non-test, non-generated) code, with high")
    print("production fan-in and NO test that directly calls them:\n")
    for name, fqn, fp, prod, test in fragile[:12]:
        print(f"  {name:28}  {prod:3} prod callers, {test} direct tests   {fp}")

    if fragile:
        top = fragile[0]
        print("\n" + "-" * 78)
        print("Sharpest finding:")
        print(f"  `{top[1] or top[0]}`")
        print(f"  in {top[2]}")
        print(f"  is called by {top[3]} production definitions, yet NO test directly")
        print(f"  exercises it. A change here would auto-merge with no direct safety net.")
        print("  (Honest caveat: 'direct' = a test that calls it in the call graph;")
        print("   indirect coverage via a tested caller is possible and not counted.)")
    else:
        print("  (none found at this threshold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
