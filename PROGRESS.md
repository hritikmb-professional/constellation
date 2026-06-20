# Constellation Implementation Progress

**Date:** June 16, 2026 (Day 1 of 8-day hackathon)  
**Status:** Validated prototype — four-lens composition validated against real Orbit data, with a deferred deployment layer

---

## ✅ COMPLETED (Today)

### 1. Project Initialization
- [x] Git repo created (`constellation/`)
- [x] Folder structure scaffolded
- [x] MIT license in place
- [x] Initial commit (5a362b7)

### 2. Core Documentation
- [x] **AGENTS.md** — System overview, judges read this first
- [x] **README.md** — Setup, architecture, development guide
- [x] **proposal.md** — Full business + technical proposal

### 3. Agent Scaffolds
- [x] **Impact Agent** — Fully implemented
  - Input: MR with changed symbols
  - Output: Blast radius, affected owners, change-failure heuristic
  - Status: Works against real Orbit data — recursive transitive traversal over `gl_edge` CALLS; the only lens that queries Orbit, materializes a `MaterializedSubgraph`
  - Queries: Ready in `shared/queries.sql` (Query 1a-d)

- [x] **Provenance Agent** — Fully implemented
  - Input: Finding with affected symbol
  - Output: Exposure scope (real composition over Impact's subgraph) + lineage chain (representative — pending SDLC enrichment at deploy), confidence score
  - Status: Works — EXPOSURE reuses Impact's subgraph; the LINEAGE chain (finding → MR → author) is representative data because the SDLC tables don't exist locally
  - Queries: Ready in `shared/queries.sql` (Query 2a-c)
  - Bonus: Mermaid graph generator for lineage visualization (representative data)

- [x] **Compliance Agent** — Implemented
  - Consumes Impact's subgraph (no re-query); detects control-boundary crossings by file-path matching (security/auth/payments)
  - Queries drafted in `shared/queries.sql` (Query 3a-b)
  - Status: SDLC controls (non-author approval, passing pipeline) reported NEEDS_GITLAB_DATA, enforced at deploy

- [x] **Ownership Agent** — Implemented
  - Consumes Impact's subgraph (no re-query); computes bus factor + ownership concentration over structural code areas (module/crate path prefixes)
  - Model drafted in `shared/queries.sql` (Query 4a-b)
  - Status: Owners are structural code-area prefixes; CODEOWNERS enrichment pending at deploy (not real git authorship)

### 4. Shared Query Core
- [x] **queries.sql** — All Orbit queries drafted
  - Pattern 1: Recursive transitive dependents over `gl_edge` CALLS (Impact)
  - Pattern 2: Pathfinding lineage (Provenance) — queries SDLC tables (MR/author); deploy-time / not yet available locally
  - Pattern 3: Standing compliance queries (Compliance) — SDLC approval/pipeline checks are deploy-time / not yet available locally
  - Pattern 4: Ownership concentration / bus factor (Ownership)
  - Bonus: Confidence scoring metrics

### 5. Orchestrator
- [x] Event routing (MR opened → Impact, Finding created → Provenance)
- [x] Verdict composition (downstream lenses consume Impact's materialized subgraph without re-querying)
- [x] Markdown formatting with evidence trails
- [x] Mermaid graph generation for vulnerability lineage (representative data — pending SDLC enrichment at deploy)

---

## 🚧 IN PROGRESS

### Next 2-3 Days (Days 2-3)

**Phase 2: Orbit Integration**
- [x] Install Orbit Local (Orbit binary v0.75.1)
- [x] Clone gitlab-org/orbit/knowledge-graph
- [x] Run `orbit index .` to build graph (16,275 definitions, single repo)
- [x] Dump actual schema: 6 tables (`gl_definition`, `gl_edge`, `gl_file`, `gl_directory`, `gl_imported_symbol`, `_orbit_manifest`)
- [x] Update queries with real column names
- [x] Test queries against real Orbit data

**Phase 3: Agent Integration**
- [x] Replace mock data with real Orbit queries (Impact recursive traversal over `gl_edge`)
- [x] Implement orbit_client.py (REST API wrapper)
- [x] Test Impact agent on real data
- [ ] Test Provenance lineage against SDLC tables (deferred — no `gl_merge_request` / `gl_user` / `gl_finding` locally)

---

## 📋 ROADMAP (Days 4-8)

### Days 4-5: Flow & Orchestrator
- [x] Create flow definition (orchestrator/flow.yml → run_constellation.py runs the same orchestrator the tests exercise)
- [ ] Implement GitLab webhook triggers (deferred to deploy)
- [ ] Post verdicts as MR comments (deferred to deploy)
- [ ] Create remediation work items (deferred to deploy)
- [ ] Test end-to-end on real GitLab instance (deferred to deploy)

### Day 5-6: Polish & Catalog
- [ ] Write agent.yml files for all agents
- [ ] Excellent system-prompt.md for each agent
- [ ] Publish to GitLab AI Catalog
- [ ] Zero-config setup validation

### Day 7: Demo & Proof
- [x] Run Constellation on gitlab-org/orbit/knowledge-graph (real Orbit index, 16,275 definitions)
- [ ] Capture before/after metrics
- [ ] Find and optionally fix a real issue
- [ ] Create MR tagged `orbit::hackathon`

### Day 8: Video & Submission
- [ ] Record 3-min demo video
- [ ] Devpost submission (problem, solution, what built, what next)
- [ ] Final polish and review

---

## 📊 Test Results

### Impact Agent (real Orbit data)
```
✅ Test passed: agents/impact/impact_agent.py
- Changed symbols: allow_all + compile (keystones)
- Transitive dependents: 510 across 6 files (recursive over gl_edge CALLS, terminates at depth 3, <60ms)
- Change-failure heuristic: 45% (structural: base 5% + 6%/keystone + blast-magnitude + chokepoint + critical-path)
- Keystones: allow_all (191 callers, caller-count #1, PageRank centrality #49), compile (176, #2, PageRank #28)
- Chokepoints (cut vertices): compile isolates 292; run_query_with_security isolates 221 (not a keystone)
- Verdict: CRITICAL → Decision Gate BLOCK
- Output: Formatted markdown ready for MR comment
```
allow_all alone: 276 transitive dependents → CRITICAL (keystone + chokepoint, bus factor 1, 100% concentration, security boundary) → BLOCK.

### Provenance Agent
```
✅ Test passed: agents/provenance/provenance_agent.py
- EXPOSURE (real): reuses Impact's subgraph
- LINEAGE chain (representative — pending SDLC enrichment at deploy):
    CVE → finding → introducing MR !2456 → author alice@example.com
- Output: Formatted markdown + mermaid graph (lineage is representative data)
```

---

## 🎯 Critical Path

**GO/NO-GO Gate:** Orbit setup — CLEARED
- Orbit Local v0.75.1 indexed (16,275 definitions); Impact runs real recursive traversals
- SDLC half deferred to deploy (no `gl_merge_request` / `gl_user` / `gl_finding` / `gl_pipeline` tables locally)

**Single-Thread Bottleneck:** RESOLVED — schema confirmed (6 tables), queries validated against real data

**Risk Mitigation:**
- Four lenses validated against real Orbit data (5 integration tests passing)
- Query templates validated (queries.sql)
- SDLC enrichment deferred, not faked (CODEOWNERS/authorship, MR/author lineage, pipeline/approval checks)

---

## 📝 Code Quality Checklist

- [x] Clean agent implementations (Impact + Provenance)
- [x] Proper error handling and logging
- [x] Type hints throughout
- [x] Docstrings on all public methods
- [x] Dataclass contracts for verdicts
- [x] Markdown formatting functions
- [ ] Unit tests (TODO: write tests for agents)
- [x] Integration tests — 5 passing (Tests 1, 3, 4 and the full scenario exercise real Orbit data; Test 2 exercises the representative provenance lineage)

---

## 🎁 Bonus Features (Optional)

- [x] Mermaid graph generation for vulnerability lineage (done in Provenance)
- [ ] "Review debt" analysis (surface under-reviewed MRs by blast radius)
- [ ] Self-verify loop (re-query after fix merged, auto-close work item)
- [ ] Slack notifications for critical findings
- [ ] PagerDuty escalation for high-severity vulnerabilities

---

## 📂 File Summary

| File | Lines | Status | Description |
|------|-------|--------|-------------|
| AGENTS.md | 380 | ✅ Complete | System overview (judges read first) |
| README.md | 320 | ✅ Complete | Setup + development guide |
| shared/queries.sql | 410 | ✅ Complete | All Orbit queries (4 patterns) |
| agents/impact/impact_agent.py | 200 | ✅ Complete | Blast radius computation |
| agents/provenance/provenance_agent.py | 230 | ✅ Complete | Vulnerability lineage + exposure |
| agents/compliance/compliance_agent.py | 20 | ✅ Complete | Control-boundary crossings (path match); SDLC checks NEEDS_GITLAB_DATA |
| agents/ownership/ownership_agent.py | 30 | ✅ Complete | Bus factor + concentration over structural code areas |
| orchestrator/orchestrator.py | 180 | ✅ Complete | Event routing + verdict composition |
| **TOTAL** | **~1770** | | |

---

## 💡 Next Immediate Steps

Orbit setup, schema confirmation, query validation, real Orbit client integration, and flow.yml are DONE. Remaining work is the deferred deployment layer:

1. Wire GitLab webhook trigger
2. Post the composed verdict as an MR comment
3. SDLC enrichment: CODEOWNERS/git authorship, MR/author lineage edges, pipeline/approval compliance checks
4. Capture before/after demo metrics

---

## 🤝 Composition Architecture (Integrative Differentiator)

The orchestrator implements the **shared-context composition model**:

```
MR Opened Event
    ↓
Orchestrator receives event
    ↓
Impact Agent runs (the only lens that queries Orbit)
    ├─ Queries: recursive transitive dependents over gl_edge CALLS
    └─ Materializes: MaterializedSubgraph (510 dependents across 6 files)
    ↓
Three downstream lenses consume Impact's subgraph WITHOUT re-querying Orbit:
    ├─ Ownership   → bus factor + ownership concentration (structural code areas)
    ├─ Compliance  → control-boundary crossings by file-path match
    └─ Provenance  → EXPOSURE (real) within blast radius;
                     LINEAGE (representative — pending SDLC enrichment at deploy)
    ↓
Orchestrator composes verdicts (blended risk = 0.6*peak + 0.4*avg)
    ├─ "This change reaches 510 things across 6 files"
    ├─ "These keystones cross control boundaries / concentrate ownership"
    └─ "Risk level: CRITICAL → Decision Gate BLOCK"
    ↓
Posted to MR as single verdict with evidence trails
```

**Why this matters:**
- NOT four isolated tools (❌ "four projects in a trench coat")
- YES one query engine, four lenses, shared context (✅ real composition)
- Impact materializes the subgraph once; the three downstream lenses consume it without re-querying Orbit (verified by integration Test 4)
- The fresh idea is integrative/packaging-level: each lens has mature prior art (Sourcegraph=impact, CodeScene=bus factor, Endor/Snyk=reachability, OPA + GitLab approval policies=compliance gate, Joern/CodeQL/Moderne="materialize once, project many"). What is genuinely new here is the specific combination on Orbit's unified graph — treating ONE reachability set simultaneously as blast radius, compliance surface, and vuln exposure

---

## 🚀 Go-Live Readiness

**Summary:**
- **Four lenses:** ✅ Impact + Ownership + Compliance + Provenance composing over real Orbit data
- **Orbit data:** ✅ Real index queried (16,275 definitions, v0.75.1); SDLC lineage uses representative data pending deploy
- **Integration tests:** ✅ 5 integration tests passing (Tests 1, 3, 4 + full scenario exercise real Orbit data; Test 2 exercises representative provenance lineage)
- **Query core:** ✅ All patterns validated in SQL
- **Orchestrator:** ✅ Composition model implemented (blended risk + Decision Gate)
- **Deploy path:** ✅ flow.yml → run_constellation.py runs the SAME orchestrator the tests exercise; compose_verdict.py delegates to that same orchestrator logic (no divergent, weaker path)
- **Webhook + MR comment:** 📋 Deferred (not faked)
- **SDLC enrichment:** 📋 Deferred — CODEOWNERS/git authorship, MR/author lineage edges, pipeline/approval compliance checks
- **AI Catalog:** 🚧 (pending deploy)
- **Demo readiness:** 🚧 (pending deploy wiring)

**Status:** Four-lens composition validated against real Orbit data. Remaining work is the deferred deployment layer (webhook trigger, MR-comment posting, SDLC enrichment).

**Remaining deploy steps (deferred, not faked):**
1. Wire GitLab webhook trigger
2. Post the composed verdict as an MR comment
3. SDLC enrichment: CODEOWNERS/git authorship, MR/author lineage edges, pipeline/approval compliance checks

**Estimated:** On track for June 24 deadline. The orchestrator and four-lens composition are validated; the deferred deployment layer is the remaining critical path.

---

**Status:** Four-lens composition validated against real Orbit data. The deferred deployment layer (webhook + MR comment + SDLC enrichment) is the remaining work.

