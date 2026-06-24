# Constellation — submission writeup

> Graph-native merge-request intelligence on GitLab Orbit. It answers the question every reviewer actually has - *"if I merge this, what could it break, who owns it, and has it hurt us before?"* - by reasoning over the real code-property graph, and it gates the merge accordingly.

---

## Elevator pitch

Constellation runs in GitLab CI on every merge request. It indexes the repo with **GitLab Orbit's knowledge graph**, runs a four-lens analysis over exactly the symbols you changed, and posts a verdict comment that can **block the merge**. The difference from every linter and CODEOWNERS rule: it scores risk by **what you changed and how much depends on it**, computed from the actual call graph - not by file paths or string matching. A one-line comment on a function called 509 times sails through; a signature change to that *same* function is blocked.

## Inspiration

Code review tools tell you *where* a change is, never *what it means*. CODEOWNERS knows who owns a file. Linters know your style. SonarQube knows your smells. None of them can answer the question a senior engineer asks in two seconds: **"what is downstream of this, and is this change the kind that breaks downstream things?"** That answer lives in the call graph - and GitLab Orbit finally exposes the call graph as a queryable knowledge graph. Constellation is what you build when you take that graph seriously.

## What it does

On every merge request, four lenses run over a single shared analysis:

- **Impact** — the real transitive blast radius via a recursive `CALLS`-edge traversal; **keystones** (high-fan-in single points of failure) and **chokepoints** (true articulation points whose failure isolates downstream code - distinct from fan-in).
- **Ownership** — bus-factor / concentration of the blast radius, now backed by **real `git blame`** authorship weighted by call centrality (anonymized).
- **Compliance** — whether the blast radius reaches a sensitive control boundary.
- **Provenance** — vulnerability exposure scoped to the same blast radius.

These compose: Impact materializes the blast-radius subgraph **once**, and the other three lenses *consume* it instead of re-querying Orbit. The verdict ends in an actionable **Decision Gate** — AUTO_APPROVE / REVIEW / SENIOR_REVIEW / BLOCK — posted as an MR comment, and `CONSTELLATION_ENFORCE=1` turns a BLOCK into a failed pipeline.

**The core idea — the edit-semantics gate.** Risk = *topology* × *what-changed*. We deterministically classify each diff edit as cosmetic / body-edit / contract-break by reading the before/after content, and multiply the topology risk by an edit-danger factor (0.0 / 0.5 / 1.0). This is the whole thesis in one demo: the **same** function `compile` (509 transitive dependents) **AUTO_APPROVEs on a comment and BLOCKs on a signature change.** Topology alone sees 509 either way; Constellation sees the difference.

## How we built it

- **GitLab Orbit Local (v0.75.1)** as the data plane - a DuckDB code-property graph. Every signal is a SQL query against the real graph (`gl_definition`, `gl_edge` with `CALLS`).
- **Graph algorithms, correctly implemented** (`shared/graph_analysis.py`): a depth-bounded recursive CTE for transitive blast radius (terminates on cycles), PageRank with dangling-mass redistribution for eigenvector centrality, and remove-and-recount articulation-point detection for chokepoints.
- **The edit-semantics classifier** reads each changed function's signature across the diff and labels the edit deterministically - no LLM, fully reproducible.
- **Two history lenses, grounded in git, not the graph:** a **scar prior** (mines reverts / hotfixes / fix-density near the change and adds a bounded, *receipted* risk nudge) and **git-truth ownership** (real blame-based bus factor and single-point-of-failure, anonymized by default).
- **Deployed through GitLab CI** (`.gitlab-ci.yml` + `ci/run_ci.py` + `ci/gitlab_post.py`): downloads and checksum-verifies Orbit, indexes the repo, runs the orchestrator on the MR's changed symbols, posts the verdict.

## Evidence it actually works

Everything below is reproducible from the repo against the real Orbit graph:

- **Calibration backtest** — replayed the last **25 merged MRs** of the Orbit repo: **60% AUTO_APPROVE, 28% senior review, 4% BLOCK.** The single BLOCK was an MR that changed **8 function signatures** touching ~1,310 dependents - a genuine catch, not noise.
- **It reviews itself** — Constellation indexes and reviews its *own* code, naming the 7 real callers of a changed function with line numbers.
- **Latent-risk scan** — of the 18 most-called production functions in the Orbit repo, **12 have no direct test coverage** (rendered as an SVG risk map).
- **Scar prior** correctly surfaces the query-engine compiler passes as the most-patched code, citing the exact fix-commit SHAs as receipts.
- **7 integration tests** pass against a live Orbit binary, including a regression test that locks the comment→AUTO_APPROVE / signature→BLOCK behavior.

## What makes it different

CODEOWNERS, Danger, SonarQube, and GitLab's own SAST all answer *"where is this change?"* Constellation answers *"what does this change do, to what, owned by whom, with what history?"* - and it does it natively on Orbit, the thing the hackathon is about. The composition (materialize once, four lenses consume) is an architecture, not four bots in a trench coat.

## What we're honest about (because trust is the product)

A review tool that over-flags gets routed around. So we state the limits plainly, in the output:

- Orbit Local has no SDLC tables, so the Provenance `MR → author` lineage and Compliance approval checks are **representative**, labelled as such.
- The call graph is from static analysis, so reachability is a strong **heuristic**, not a proof (we say "no *direct* test," not "untested").
- Blast radius is resolved by name, so it **unions same-named definitions** - an upper bound, disclosed.
- The change-failure score is a transparent weighted heuristic plus a **capped, receipted** historical prior - explicitly *not* a calibrated probability.

## What's next

- SDLC enrichment once Orbit-Remote exposes merge-request / author / pipeline tables (turns the two representative lenses fully real).
- FQN-level symbol resolution to make the blast radius exact rather than an upper bound.
- A structural call-graph diff (base vs head) so the gate reasons about edges *added and severed*, not just signatures.

## Built with

Python · GitLab Orbit Local (DuckDB code-property graph) · GitLab CI/CD · GitLab Merge Request API · PageRank / articulation-point graph algorithms · git (blame & history mining).
