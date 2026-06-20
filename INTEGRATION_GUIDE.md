# Constellation-Orbit Integration Guide

**Quick Reference:** Swapping mock Orbit data for real Orbit queries in 5 minutes.

> **Status:** The Impact lens is already wired to a real Orbit Local index of
> `gitlab-org/orbit/knowledge-graph` (16,275 definitions, Orbit binary v0.75.1,
> single repo) and validated by 5 passing integration tests. This guide remains
> the reference for the client swap and for the SDLC-enrichment work still
> **deferred** at deploy. Steps that query SDLC tables (merge requests, findings,
> users, pipelines) are **deploy-time / not-yet-available** — those tables do not
> exist in the local index.

---

## Phase 1: Validate Schema (Pre-Integration)

When Orbit is available, immediately capture the schema:

```bash
# In WSL or Docker:
orbit sql "SELECT column_name, data_type FROM information_schema.columns 
           WHERE table_name = 'gl_definition' ORDER BY ordinal_position"
```

Save output to `ORBIT_SCHEMA.txt` in the repo root.

The local index exposes exactly **6 tables**: `gl_definition`, `gl_edge`,
`gl_file`, `gl_directory`, `gl_imported_symbol`, and `_orbit_manifest`. There are
**no SDLC tables** (no `gl_merge_request`, `gl_user`, `gl_finding`, or
`gl_pipeline`); any step below that references those is **deploy-time, not yet
available**.

---

## Phase 2: Update Queries (30 minutes)

### Step 1: Compare Mock vs Real Schema

**Mock schema** (in `shared/orbit_mock.py`):
```python
{
  "total_dependents": 14,
  "affected_services": 3,
  "service_ids": ["api-svc", "data-svc", "worker-svc"],
}
```

**Real schema** (from `orbit sql DESCRIBE gl_definition`):
- Likely has actual column names like `name`, `file_id`, `project_id`, etc.
- May differ from mock; update `shared/queries.sql` accordingly

### Step 2: Update SQL Queries

**File:** `shared/queries.sql`

Update Query 1b (transitive dependents). Transitive dependents are a recursive
traversal over `gl_edge` rows where `relationship_kind = 'CALLS'` (see
`shared/queries_real.sql`):
```sql
-- BEFORE (mock placeholder):
SELECT id FROM gl_definition WHERE name IN (...)

-- AFTER (real schema: walk CALLS edges in gl_edge):
SELECT e.source_id
FROM gl_edge e
INNER JOIN gl_definition d ON d.id = e.target_id
WHERE e.relationship_kind = 'CALLS' AND d.name IN (...)
```

**Validation:**
```bash
orbit sql "SELECT COUNT(*) FROM gl_definition LIMIT 1"
# Should return actual count, not 0
```

### Step 3: Test Each Query

```bash
# Query 1a: Direct dependents (real — CALLS edges in gl_edge)
orbit sql "SELECT source_id FROM gl_edge WHERE relationship_kind = 'CALLS' AND target_id = 123"

# Query 2a: Lineage — DEPLOY-TIME ONLY (no gl_finding table locally; SDLC enrichment pending)
# orbit sql "SELECT * FROM gl_finding JOIN gl_definition ..."

# Query 3a: Compliance approvals — DEPLOY-TIME ONLY (no gl_merge_request table locally)
# orbit sql "SELECT * FROM gl_merge_request WHERE ..."

# Query 4a: Ownership — inbound caller-count centrality (real — CALLS edges in gl_edge)
orbit sql "SELECT COUNT(*) AS inbound FROM gl_edge WHERE relationship_kind = 'CALLS' AND target_id = def_id"
```

---

## Phase 3: Swap Client (5 minutes)

### Step 1: Update Agent Imports

**File:** `agents/impact/impact_agent.py`

```python
# BEFORE (line 10):
from shared.orbit_mock import MockOrbitClient
def __init__(self, orbit_client=None):
    if orbit_client is None:
        self.orbit_client = MockOrbitClient()

# AFTER:
from shared.orbit_client import OrbitClient  
def __init__(self, orbit_client=None):
    if orbit_client is None:
        self.orbit_client = OrbitClient()
```

**File:** `agents/provenance/provenance_agent.py`

Same change as above.

**File:** `orchestrator/orchestrator.py`

```python
# BEFORE:
from shared.orbit_mock import MockOrbitClient
orchestrator = Orchestrator(orbit_client=MockOrbitClient(), ...)

# AFTER:
from shared.orbit_client import OrbitClient
orchestrator = Orchestrator(orbit_client=OrbitClient(), ...)
```

### Step 2: Verify Imports Work

```bash
cd constellation
python -c "from shared.orbit_client import OrbitClient; c = OrbitClient(); print('OK' if c.health_check() else 'FAIL')"
```

---

## Phase 4: Validate End-to-End (30 minutes)

### Step 1: Run Integration Tests
```bash
python tests/integration_test.py
```

There are **5 integration tests, all passing**. Tests 1, 3, 4 and the full
scenario exercise **real Orbit data** with non-vacuous assertions; Test 2
(Provenance) exercises the **representative lineage** (the SDLC tables needed for
real finding→MR→author lineage do not exist locally).

Expected output:
- TEST 1 (Impact): real transitive dependents from the Orbit repo
- TEST 2 (Provenance): representative vulnerability lineage (pending SDLC enrichment at deploy)
- TEST 3 & 4 + full scenario: compose over real Impact data

### Step 2: Spot-Check Results

```bash
# Check Impact agent output
python agents/impact/impact_agent.py << 'EOF'
{
  "mr_id": "mr-test",
  "changed_symbols": ["process_config"]
}
EOF

# Should print real transitive dependents from Orbit repo, e.g.:
# - validate_request (depth 1)
# - load_config (depth 2)
# - etc.
```

### Step 3: Verify Confidence Scores

Mock always returns 0.95 confidence. Real Orbit should return varying scores based on:
- Coverage of code graph (are all symbols indexed?)
- Lineage completeness (can we trace introducing MRs?)
- Deployment data availability

---

## Phase 5: Troubleshooting

### Problem: OrbitClient.query() returns empty dict

**Cause:** Real Orbit queries don't match schema

**Fix:**
1. Run `orbit sql "SELECT * FROM gl_definition LIMIT 1"` 
2. Compare actual columns to our query in `shared/queries.sql`
3. Update query with real column names
4. Retest: `orbit sql "SELECT COUNT(*) FROM gl_definition"`

### Problem: Integration tests fail with connection error

**Cause:** Orbit Local process not running or schema not indexed

**Fix:**
```bash
# Restart Orbit indexing
orbit index /path/to/orbit/knowledge-graph
orbit sql "SELECT COUNT(*) FROM gl_definition"
# Wait for count to stop increasing, then retest
```

### Problem: Tests pass but results look wrong (e.g., 0 dependents)

**Cause:** Queries are executing but returning empty result sets

**Fix:**
1. Verify schema is correct: `orbit sql "SHOW TABLES"` (expect the 6 tables above)
2. Check if indexing is complete: `orbit sql "SELECT COUNT(*) FROM gl_definition"` (expect 16,275)
3. Validate query manually: `orbit sql "SELECT * FROM gl_edge WHERE relationship_kind = 'CALLS' LIMIT 1"`
4. Update queries based on actual schema

---

## Integration Checklist

- [ ] WSL/Docker setup complete, Orbit running
- [ ] Schema dumped to `ORBIT_SCHEMA.txt`
- [ ] `shared/queries.sql` updated with real column names
- [ ] Test each query manually via `orbit sql`
- [ ] Agent imports changed (mock → OrbitClient)
- [ ] `python tests/integration_test.py` passes
- [ ] Spot-check: real blast radius computed (not mock 14 dependents)
- [ ] Spot-check: lineage uses representative data (real finding→MR→author lineage is deferred — pending SDLC enrichment at deploy)
- [ ] Flow integration ready (`orchestrator/flow.yml` → `orchestrator/run_constellation.py` runs the same orchestrator the tests exercise)
- [ ] Demo on real repository working

---

## Expected Differences: Mock vs Real

### Impact Agent

**Mock:**
- Always returns exactly 14 dependents
- Always 3 services
- Always 8% failure rate

**Real (measured against the Orbit repo):**
- `allow_all` + `compile`: 510 transitive dependents across 6 files (recursive over
  `gl_edge` CALLS; terminates at depth 3; query <60ms). `allow_all` alone: 276.
- Keystones are detected by **caller-count** (`allow_all` 191 inbound, #1; `compile`
  176, #2) and additionally annotated with **real PageRank centrality** over the
  whole call graph (`allow_all` #49, `compile` #28 — the two disagree, which is
  the point). Cut-vertex **chokepoints** are computed separately (e.g.
  `run_query_with_security` isolates 221 defs but is not a keystone).
- Change-failure rate is a transparent **structural heuristic**, not a historical
  or learned model: base 5% + 6%/keystone + blast-magnitude + chokepoint +
  critical-path terms (=> 45% for `allow_all`+`compile`).

### Provenance Agent

**Mock:**
- Lineage always: Finding → Symbol → Def → MR → Author (5 steps)
- Always 2 exposed services

**Real:**
- EXPOSURE is real composition — it reuses Impact's materialized subgraph, so it
  varies by which code actually reaches the vulnerable symbol.
- The LINEAGE chain (finding → introducing MR → author; the `alice@example.com` /
  `!2456` / CVE example) is **representative data** — the SDLC tables it needs do
  not exist locally. Real lineage is **pending SDLC enrichment at deploy**.

### Confidence Scores

**Mock:**
- Impact: always 0.95
- Provenance: always 0.99

**Real:**
- Impact: 0.70-0.99 depending on graph completeness
- Provenance: 0.80-0.99 depending on lineage traceability
- May be lower if repos are private or data incomplete

---

## Timeline

- **WSL/Docker setup:** 1-2 hours (includes system reboot)
- **Schema dump + query update:** 30 minutes
- **Client swap + testing:** 30 minutes
- **Total:** ~2.5 hours to full real Orbit integration

**Can happen in parallel with:** flow.yml design, webhook setup, output formatting

---

## References

- Query debugging: `shared/queries.sql` comments
- Agent contracts: `agents/*/agent.md` (system prompts)
- Mock data structure: `shared/orbit_mock.py` (reference)
- Real client structure: `shared/orbit_client.py` (backends)

