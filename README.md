<div align="center">

# 🌌 Constellation

### Graph-native DevOps intelligence for GitLab

**Constellation reads GitLab Orbit's code graph and answers, on every merge request, the questions a senior reviewer would ask but rarely has time to — in under a second, as a comment on the MR, ending in a decision.**

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Built on GitLab Orbit](https://img.shields.io/badge/Built%20on-GitLab%20Orbit-FC6D26?logo=gitlab&logoColor=white)
![Tests](https://img.shields.io/badge/integration%20tests-5%2F5%20passing-success)
![Status](https://img.shields.io/badge/status-validated%20prototype-blue)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## What it does

A diff tells you *what* changed. Constellation tells you what it **means** — by traversing the dependency graph, not just reading lines:

| Lens | The question it answers |
|------|------------------------|
| **🎯 Impact** | What actually breaks if this changes? (true transitive blast radius, keystones, structural chokepoints) |
| **👤 Ownership** | Who carries this, and is the risk dangerously concentrated? (bus-factor) |
| **🛡️ Compliance** | Does this change cross a security / control boundary? |
| **🔬 Provenance** | If there's a vulnerability here, how far does it actually reach? |

All four run off **one shared graph traversal**, and the result is not a dashboard — it's an enforceable **Decision Gate**: `AUTO-APPROVE` the safe changes, `BLOCK` the dangerous ones.

---

## See it in action

Running Constellation on a real change to GitLab Orbit's own codebase (`allow_all` + `compile`) produces this MR comment:

```markdown
# Constellation Analysis
**Risk Level:** CRITICAL

> ## Decision: [X] BLOCK MERGE
> Critical risk: do not merge without sign-off.

## Impact Analysis
Blast Radius: 510 transitive dependents across 6 files
- `…/server/redaction.rs` (67 affected) [!] critical path
- `…/data_correctness/security.rs` (57 affected) [!] critical path
- [!] Keystone `allow_all` (191 callers, caller-count #1, PageRank centrality #49)
- [!] Keystone `compile`  (176 callers, caller-count #2, PageRank centrality #28)

Chokepoints (cut vertices — failure isolates downstream code):
- `compile` isolates 292 definitions if it fails (changed by this MR)
- `run_query_with_security` isolates 221 definitions if it fails   ← not a keystone

Change-Failure Risk: 45%

## Ownership Risk
Bus factor: 1 owning area | 100% concentrated in `crates/integration-tests`
Risk: HIGH — concentration sits on a keystone

## Compliance
Boundaries crossed: security | MEDIUM — controls need GitLab data at deploy
```

The sharp part: `run_query_with_security` **isn't a keystone** (it isn't called by many things) — but the cut-vertex analysis flags it as a structural single point of failure isolating 221 definitions. Plain review, and fan-in counting, never see it.

---

## What makes it different

- **Composition, not four tools in a trench coat.** Impact traverses Orbit **once** and materializes a blast-radius subgraph; Ownership, Compliance, and Provenance **consume that object without re-querying**. This is asserted by an integration test, not just described.
- **Real graph theory.** Beyond counting callers, Constellation computes **cut vertices** (articulation points) and **PageRank** centrality over the call graph — surfacing single points of failure that fan-in counting misses.
- **A control, not a report.** The blended-risk model (`0.6·peak + 0.4·avg`, so one critical signal can't be averaged away) drives a Decision Gate a CI pipeline can enforce.
- **Honest by construction.** Every verdict carries confidence scores and an evidence trail; data that needs a live GitLab instance is labelled (`representative` / `pending at deploy`) rather than faked.

---

## Validated results (real Orbit data)

Measured against a real Orbit Local index of `gitlab-org/orbit/knowledge-graph`:

| Metric | Value |
|--------|-------|
| Definitions indexed | **16,275** |
| Transitive blast radius (`allow_all`+`compile`) | **510** across 6 files |
| Blast-radius query time | **< 60 ms** (recursive traversal over `gl_edge` CALLS) |
| Top chokepoint | `compile` — isolates **292** definitions |
| Integration tests | **5 / 5 passing** on real Orbit |

---

## Quick start

```bash
# Run the full system on real data (Impact → Ownership → Compliance → Provenance → Decision Gate)
python demo.py

# Run the integration suite (auto-detects a real Orbit binary; falls back to mock offline)
python tests/integration_test.py
```

No third-party Python dependencies — the analysis runs on the standard library plus the Orbit CLI.

---

## Deploy on GitLab (merge-request analysis)

Constellation ships a ready GitLab CI pipeline ([`.gitlab-ci.yml`](.gitlab-ci.yml)) that, on every MR:

1. Downloads + checksum-verifies the Linux Orbit binary and **indexes the repo**.
2. **Extracts the real changed symbols** from the MR diff (mapping diff hunks to Orbit definitions).
3. Runs the four-lens orchestrator and **posts the verdict as an MR comment**.
4. Optionally **fails the pipeline on a `BLOCK` verdict** (`CONSTELLATION_ENFORCE=1`) — turning the gate into a real merge control.

Setup:

```
Settings → CI/CD → Variables → add  CONSTELLATION_TOKEN
   (project access token, `api` scope, Reporter role; Masked, NOT protected)
```

Open a merge request → the pipeline runs → Constellation comments. A GitLab Duo Agent Platform flow ([`.gitlab/flow.yml`](.gitlab/flow.yml)) is also provided for the agent-platform deployment path.

---

## Status — what's real vs. deferred

Constellation is an **honestly-scoped validated prototype**, not a finished product. We keep this explicit:

**Real today (validated against a live Orbit index, 5 integration tests):**
- All four lenses, the shared-subgraph composition, blended risk, and the Decision Gate
- Recursive transitive blast radius, keystone detection, PageRank centrality, cut-vertex chokepoints
- Real changed-symbol extraction from an MR diff; verdict posting via CI

**Deferred — needs a live GitLab/Orbit-Remote instance (not faked, labelled in output):**
- SDLC enrichment: the Provenance lineage's `MR → author` half, and Compliance's approval/pipeline checks (the tables aren't in Orbit Local)
- Calibrating the change-failure heuristic against real merge/incident history

---

## Architecture

```
Event (MR opened)
      │
      ▼
Orchestrator ─ Impact traverses Orbit once → materializes a blast-radius subgraph
      │            │
      │            ├─► Ownership   ┐
      │            ├─► Compliance  ├─ consume the subgraph (no re-query)
      │            └─► Provenance  ┘
      │
      ▼
Blended risk → Decision Gate → verdict posted as an MR comment
      │
      ▼
GitLab Orbit — unified SDLC + code property graph (DuckDB)
```

## Project structure

```
constellation/
├── agents/
│   ├── impact/        # blast radius, keystones, chokepoints, PageRank, subgraph
│   ├── ownership/     # bus-factor / concentration (consumes the subgraph)
│   ├── compliance/    # control-boundary detection (consumes the subgraph)
│   └── provenance/    # vulnerability exposure + lineage (consumes the subgraph)
├── orchestrator/
│   ├── orchestrator.py      # composition, blended risk, Decision Gate, markdown
│   └── run_constellation.py # single in-process entry (used by CI + the flow)
├── shared/
│   ├── orbit_real_client.py # real Orbit SQL client (recursive CTEs, escaping)
│   └── graph_analysis.py    # cut-vertex (articulation) + PageRank
├── ci/                # GitLab CI: changed-symbol extraction + verdict posting
├── tests/integration_test.py
├── .gitlab-ci.yml     # merge-request analysis pipeline
└── AGENTS.md          # full system overview
```

## Tech stack

**Python** · **GitLab Orbit** (code-property graph on DuckDB) · **GitLab CI / Duo Agent Platform** · standard-library only (no runtime deps).

---

## License

MIT — see [LICENSE](LICENSE).

<div align="center">

**Constellation** · Graph-native DevOps intelligence on GitLab Orbit
Team **AeroFyta** · GitLab Transcend Hackathon (Showcase Track)

</div>
