# Constellation: Graph-Native DevOps Intelligence

## System Overview

Constellation is a multi-agent system that exploits GitLab Orbit's unified SDLC-plus-code property graph to compose DevOps decisions that no single tool can make alone.

**One primitive.** Cross-domain pathfinding and impact traversal over a property graph.

**Four lenses.** Each agent applies the primitive to a different question: Impact (blast radius), Ownership (bus-factor risk), Compliance (control-boundary crossing), Provenance (vulnerability exposure & lineage).

**One verdict.** The agents compose over a **shared materialized subgraph** — Impact traverses Orbit, the three downstream lenses consume its subgraph without re-querying — and the orchestrator emits a single, evidence-backed verdict ending in an actionable **Decision Gate**.

> Validation note: all four lenses run against a real Orbit Local index of the
> `gitlab-org/orbit/knowledge-graph` repo (16,275 definitions). Numbers shown
> below are from that index. What still requires a live GitLab instance is
> labeled explicitly — we don't blur the line.

---

## The Problem

Mature DevOps teams have comprehensive tooling: vulnerability scanners, dependency analyzers, CI/CD pipelines, code-quality metrics. Yet the most valuable questions—"what will this change break?", "who carries the risk?", "does this cross a control boundary?", "is this vulnerability actually reachable?"—require synthesizing signals across several systems by hand. This is not a tool gap; it is a data-model gap.

GitLab Orbit solves the data model by unifying the SDLC and code into a single property graph. Constellation adds the intelligence layer on top.

---

## The Four Lenses

### 1. Impact lens (`agents/impact`)
**Question:** What is the true blast radius of this change?

**Input:** Merge request → changed code symbols

**Method:** Recursively query Orbit for transitive callers of each changed symbol (recursive traversal over `gl_edge` CALLS; terminates at depth 3, <60ms); group into affected files/areas; detect **keystones** (high fan-in, by inbound-call count) and **chokepoints** (cut vertices / articulation points in the induced subgraph — real graph theory, distinct from fan-in); predict change-failure risk.

**Keystone vs chokepoint** — two different SPOF questions: a keystone is *called by* many things (fan-in); a chokepoint is a definition whose *removal disconnects* part of the dependency graph (topology). A symbol can be one without the other, so both are computed. Chokepoints are found by removing each subgraph node and recounting connected components (`shared/graph_analysis.py`); each is reported with how many definitions it would isolate.

**Real output (changing `allow_all` + `compile` on the Orbit repo):**
```
Blast Radius: 510 transitive dependents across 6 files
Keystones:    allow_all (191 inbound callers, caller-count #1), compile (176 inbound callers, #2)
Chokepoints:  compile isolates 292 defs; run_query_with_security isolates 221 defs
              (run_query_with_security is NOT a keystone — fan-in misses it; topology catches it)
Change-Failure Risk: 45% (structural heuristic: base 5% + 6%/keystone + blast-magnitude + chokepoint + critical-path)
Confidence: 95%
```

Impact materializes a `MaterializedSubgraph` (root symbols, affected services, owners, keystones) that the other three lenses consume.

### 2. Ownership lens (`agents/ownership`)
**Question:** Who carries this change, and what happens if that area's maintainer leaves?

**Method:** Consumes Impact's subgraph (no re-query). Scores ownership **concentration** and **bus factor** across the owning code areas; escalates when one area owns the keystones.

**Real output (changing `allow_all`):**
```
Bus factor: 1 owning area | Concentration: 100% in crates/integration-tests
Risk: HIGH — 100% of impact concentrated in one area which owns keystone
      allow_all — severe bus-factor risk.
```

Ownership areas are **structural** code areas derived from module/crate path prefixes in the code graph (Orbit has no git/author data locally). CODEOWNERS enrichment and git authorship are **pending at deploy** on a live GitLab instance; locally it is an honest structural proxy, labeled as such.

### 3. Compliance lens (`agents/compliance`)
**Question:** Does the blast radius cross a control boundary, and are the required safeguards in place?

**Method:** Consumes Impact's subgraph. Detects **structural** boundary crossings directly from file paths (security, auth, redaction, payments). Evaluates **SDLC** controls (non-author approval, passing pipeline) when GitLab metadata is supplied; otherwise reports them as `NEEDS_GITLAB_DATA` — never a silent pass.

**Real output (changing `allow_all`):**
```
Boundaries crossed: security | MEDIUM risk — 0 violations
- [?] Sensitive boundary crossing — reaches security code, stricter controls apply
- [?] Non-author approval — enforced via GitLab at deploy
- [?] Passing pipeline   — enforced via GitLab at deploy
Triggering files: security.rs, redaction.rs
```

A confirmed failed control (when MR metadata is present) escalates to HIGH / violation.

### 4. Provenance lens (`agents/provenance`)
**Question:** Where did a vulnerability come from, and how far does it reach?

**Method:** Traces lineage (finding → symbol → definition → introducing MR → author) as a mermaid chain. The **code half** (finding → symbol → definition) is resolved from the **real** graph — the symbol maps to its actual definition with real file path, line span, kind, and inbound-caller count. The **SDLC half** (introducing MR → author) is **representative, pending deploy-time enrichment** (those tables don't exist in the local index). For **exposure**, when the finding's symbol is a root of Impact's materialized subgraph, the exposure set **is** that blast radius — real composition that reuses Impact's subgraph, not re-queried.

**Composition output (finding on the real symbol `allow_all`):**
```
Code (real, from graph): allow_all at helpers.rs:157-168 (191 inbound callers)   [real]
Lineage SDLC half:       -> MR !2456 -> alice@example.com                         [representative — pending deploy]
Exposure:                composed from Impact's subgraph (6 files), Orbit not re-queried   [real]
Confidence: 0.95
```

Each lineage step is tagged `data_source = real | representative`, and the MR-comment renderer surfaces the real code location while explicitly flagging the MR/author steps as representative — so a reviewer can never mistake the SDLC half for resolved data.

---

## Composition: The Moat (verified, not narrative)

The agents do not run in isolation. They compose over **shared context**:

1. Event arrives (MR opened, optionally carrying findings).
2. **Impact runs first** and stores `self.last_subgraph` (a `MaterializedSubgraph`).
3. The orchestrator hands that **exact object** to Ownership, Compliance, and Provenance.
4. Each lens reads the pre-assembled subgraph instead of re-traversing Orbit.
5. The orchestrator blends their risk signals and emits one verdict + Decision Gate.

**This is asserted in code, not just described.** Integration `Test 4`:
- runs one `mr_opened` event whose changed symbol also carries a finding,
- asserts `provenance.composed_from_impact is True` and that the exposure set equals Impact's materialized services,
- asserts Ownership and Compliance also ran from the same subgraph and recorded it in the evidence trail.

The three downstream lenses consume Impact's subgraph **without re-querying Orbit** (Impact itself issues a few SQL queries); the others are pure consumers. Adding a fifth lens is ~80 lines against the same subgraph, not a new product. That reuse is the moat.

---

## The Decision Gate

Every verdict ends in a machine-actionable recommendation a CI gate can enforce:

| Gate | When |
|------|------|
| `[OK] AUTO-APPROVE` | low blast radius + high confidence |
| `[~] REVIEW REQUIRED` | moderate impact |
| `[!] SENIOR REVIEW` | keystone touched or high blast radius |
| `[X] BLOCK MERGE` | critical risk (e.g., live CVE on path, severe bus factor) |

Risk is **blended** across lenses (`0.6·peak + 0.4·avg`) so one critical signal can't be averaged away. Changing `allow_all`+`compile` yields CRITICAL → **BLOCK** (510 transitive dependents, 2 keystones, 100% ownership concentration, security boundary crossed). Changing `allow_all` alone also yields CRITICAL → **BLOCK** (276 dependents, keystone + chokepoint, 100% concentration, security boundary). The gate's lower tiers (SENIOR REVIEW / REVIEW / AUTO-APPROVE) apply to milder changes — they're threshold-based, not hard-coded to these examples.

---

## Architecture

```
Layer 1: TRIGGERS (SDLC events)         — MR opened, Finding created
Layer 2: ORCHESTRATOR                    — Impact first → shares subgraph →
         (Duo Agent Platform Flow)         Ownership / Compliance / Provenance →
                                           blended risk → Decision Gate → MR comment
Layer 3: FOUR LENSES                      — Impact, Ownership, Compliance, Provenance
Layer 4: SHARED QUERY CORE               — pathfinding, traversal, aggregation
         (shared/orbit_real_client.py)     over Orbit SQL (DuckDB Local)
Layer 5: GITLAB ORBIT                     — unified SDLC + code property graph
```

---

## Data Model: Orbit Entities Used

The local Orbit schema has exactly **6 tables**: `gl_definition`, `gl_edge`, `gl_file`, `gl_directory`, `gl_imported_symbol`, `_orbit_manifest`. The SDLC tables below do **not** exist in the local index — they are not-yet-available and light up on a live GitLab instance at deploy.

| Entity | Used for | Status |
|--------|----------|--------|
| `gl_definition` | functions/classes; blast radius via callers | **Live (local)** |
| `gl_edge` (`CALLS`) | call relationships; recursive traversal & inbound-call centrality | **Live (local)** |
| `gl_file` / `file_path` | affected files, structural ownership & boundaries | **Live (local)** |
| `gl_directory` / `gl_imported_symbol` / `_orbit_manifest` | directory tree, imports, index manifest | **Live (local)** |
| `gl_merge_request` | lineage, approvals | Deploy-time (SDLC) — not in local schema |
| `gl_pipeline` / `gl_job` | compliance pipeline control | Deploy-time (SDLC) — not in local schema |
| `gl_user` | authors, approvers, CODEOWNERS enrichment | Deploy-time (SDLC) — not in local schema |
| `gl_finding` | vulnerability triggers | Deploy-time (SDLC) — not in local schema |

The code-only half runs today on Orbit Local; the SDLC half lights up on a live GitLab instance.

---

## Confidence + Evidence

Every verdict carries a confidence score, an evidence trail (one line per lens recording what it consumed), and is reproducible from the exact Orbit SQL in `shared/orbit_real_client.py`. Confidence is **not** hardcoded to 1.0 — Compliance drops to 0.6 when SDLC data is unavailable, and the system says so.

---

## Permissions

- Agents are read-only against Orbit (queries only, no mutations).
- Any work-item creation is draft, for human review.
- No auto-merge, no auto-delete. The Decision Gate recommends; humans/CI enforce.

---

## Implementation Status (honest)

**Real and tested today (5 integration tests passing):** Tests 1, 3, 4 and the full scenario exercise real Orbit data with non-vacuous assertions; Test 2 (provenance) exercises the representative lineage.
- Impact lens — real blast radius, keystone detection, change-failure heuristic
- Ownership lens — real bus-factor / concentration, consumes Impact's subgraph
- Compliance lens — real structural boundary detection, consumes Impact's subgraph
- Provenance lens — real composed exposure; lineage chain representative
- Orchestrator — shared-subgraph composition, blended risk, Decision Gate
- Output formatter — markdown + mermaid

**Requires a live GitLab instance (deferred, not faked):**
- Webhook triggers + posting the verdict as an MR comment (`orchestrator/flow.yml`)
- SDLC enrichment: CODEOWNERS/git authorship, MR/author lineage edges, pipeline/approval compliance checks

**Stretch:**
- Self-verify loop (re-query after fix merged, auto-close work item)
- Multi-repo (Orbit Remote / ClickHouse) traversal

---

## Quick Start

```bash
# 1. (optional) index a repo with Orbit Local
bin/orbit.exe index .
bin/orbit.exe sql "SELECT COUNT(*) FROM gl_definition"

# 2. run the full system on real data
python demo.py

# 3. run the test suite (auto-detects real Orbit, falls back to mock)
python tests/integration_test.py
```

---

## For Judges

This is not four tools in a trench coat. It is ONE traversal primitive applied across FOUR lenses that **share one materialized subgraph** — verified by an integration test, not asserted in a slide. The composition is the moat; the Decision Gate turns analysis into an enforceable control.

The novelty here is **integrative / packaging-level**, not fundamental. Each lens has mature prior art (Sourcegraph for impact, CodeScene for bus factor, Endor/Snyk for reachability, OPA + GitLab approval policies for the compliance gate, Joern/CodeQL/Moderne for "materialize once, project many"). What's genuinely fresh is the **specific combination on Orbit's unified graph** — treating one reachability set simultaneously as blast radius, compliance surface, and vulnerability exposure.

**Dogfooding:** run on `gitlab-org/orbit/knowledge-graph` itself. Constellation flags that changing `allow_all` concentrates 100% of a 276-dependent blast radius in a single area that owns a keystone and crosses the security boundary — a real, non-obvious risk surfaced from the host's own code in under a second.

---

## References

- GitLab Orbit: https://docs.gitlab.com/ee/subscriptions/saas/orbit/
- Duo Agent Platform: https://docs.gitlab.com/ee/ai/duo_agent_platform/
- DuckDB SQL: https://duckdb.org/docs/
