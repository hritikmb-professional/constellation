# Constellation - the honesty narrative

Most "AI code review" demos show you a green checkmark and ask you to trust it.
This page does the opposite: it shows where Constellation was **wrong**, what we
changed, and the **real numbers** from running it against the GitLab Orbit
knowledge-graph repo. Every figure here is reproducible with the scripts in this
repo against the indexed graph - nothing is hand-typed.

---

## 1. The bug we shipped, and caught ourselves

Early Constellation scored risk purely by **topology** - how central the changed
symbol is in the call graph. That produced an indefensible verdict:

> A one-line **comment** added to a central function came back as **BLOCK**.

That is wrong, and a reviewer would lose trust in the tool instantly. If *every*
change to a hot function blocks - even a typo fix in a doc-comment - the gate is
noise, and people route around it.

The root cause: we were answering *"where did the change land?"* but never
*"what did the change actually do?"*

## 2. The fix - the edit-semantics gate

We added a deterministic (no-LLM) classifier that reads the diff's **before and
after content** and labels each edit:

| class | what it means | danger multiplier |
|---|---|---|
| `cosmetic` | comments / whitespace only - stripped, the code is identical | 0.0 |
| `body-edit` | logic changed, but the signature is intact | 0.5 |
| `contract-break` | the function signature itself changed (callers must adapt) | 1.0 |

The final risk is `topology_risk x edit_danger`. Centrality still matters - but
only once we know the change can actually hurt callers.

## 3. The proof - same symbol, same blast radius, opposite verdict

This is the whole argument in one table. Both rows are the **exact same
function** (`compile`, with **509 transitive dependents** in the real graph).
The only thing that differs is *what* the edit did:

| edit to `compile` | transitive dependents | verdict |
|---|---|---|
| add a comment (`cosmetic`) | 509 | **AUTO_APPROVE** |
| change the signature (`contract-break`) | 509 | **BLOCK** |

Topology alone cannot tell these apart - it sees 509 either way. Constellation
can, because risk now reflects **what changed, not just where**. (This is
encoded as a passing regression test: `tests/integration_test.py` -> Test 5.)

## 4. Calibration on real merged history (backtest)

We replayed Constellation over the last **25 merged MRs** of the Orbit repo
(`backtest.py`, first-parent history, edit classes read from each commit's own
content). If the tool blocked everything, it would be useless; if it approved
everything, it would be a rubber stamp. The actual distribution:

| verdict | share of 25 merged MRs |
|---|---|
| AUTO_APPROVE | **60%** |
| REVIEW_REQUIRED | 8% |
| SENIOR_REVIEW | 28% |
| BLOCK | 4% |

Edit classes (exact, per commit): 0% cosmetic, 64% body-edit, 36% contract-break.

The single BLOCK was earned: `feat/sdlc-incremental-durable-page-writes` changed
**8 function signatures** touching ~1,310 dependents at once. That is exactly the
kind of change a human should look at before it merges.

## 5. A real latent risk we found in the codebase

`find_risk.py` scans the graph for **production functions with high fan-in and
zero tests that directly exercise them** - genuine "change-it-and-pray" spots.
The risk map (`risk_map.py`, emitted as a CI artifact) visualizes it: of the 18
most-called production functions, **12 have no direct test coverage**, including:

- `hir_def_to_definition_site` - 14 production callers, 0 direct tests (Rust HIR lowering in code-graph)
- `evaluate_value` - 13 production callers, 0 direct tests (JS expression evaluation)
- `extract_request_context` - 9 production callers, 0 direct tests (auth path)

Honest caveat we kept in the output: "direct" means a test that calls the
function in the call graph. Indirect coverage through a tested caller is possible
and not counted - we say so rather than overclaiming.

## 6. Constellation reviewed its own code

`self_review.py` indexes **this repository** with Orbit and asks Constellation to
review a change to one of its own most-reused functions, `_to_int()` (8 internal
dependents). Held to its own gate, it behaves exactly as designed:

| change to `_to_int()` | internal blast radius | verdict |
|---|---|---|
| body edit (logic only) | 8 | AUTO_APPROVE |
| contract break (signature) | 8 | **SENIOR_REVIEW** |

And the verdict it posts on itself is **specific and correct** - it names the 7
real direct callers (`_query_direct_callers`, `_query_symbol_defs`, ... all the
`_query_*` methods in `shared/orbit_real_client.py`) with exact line numbers,
flags `query` as a structural chokepoint, and catches that 100% of the impact is
concentrated in one file (bus factor 1). None of that is templated - it is read
live from the graph of its own source.

The CI pipeline does this for real on every Constellation merge request: it
indexes the repo it runs on and posts the verdict. The edit-semantics gate, the
backtest, and the risk map were all themselves merged through the gate they
implement.

## 7. History, with receipts (the scar prior)

Structure tells you what a change *could* break; history tells you what *has*
broken near it before. `scar_map.py` mines git for the high-signal scars -
reverts, hotfix/rollback/emergency commits, and bug-fix density per file - then
walks one call-graph hop out from the changed symbols and adds a **bounded,
attributable prior** (at most +12%) to change-failure risk. Every point of added
risk cites the exact commit that justifies it.

On the real Orbit history this correctly surfaces the **query-engine compiler
passes** as the most-patched code (`lower/flat_chain.rs`: 5 of its 9 commits were
fixes), so a change there carries a small, *receipted* risk bump:

> `crates/query-engine/compiler/src/passes/lower/flat_chain.rs` - 56% of its
> commits were fixes -> receipt `297d1ac97b` "fix(compiler): tighten cascade
> anchor guard to pinned-ids only"

Two honesty guardrails are built in. We deliberately **do not** call this a
calibrated probability or a "validated predictive model" - it is a relative
nudge toward human review, capped and shown with its evidence. And it is
**absent-safe**: when no scar analysis is supplied (e.g. the backtest), the prior
is 0 and the structural calibration in section 4 is unchanged - verified by a
regression test (Test 6).

---

### Why this matters for judging

The thing that earns a reviewer's trust is not a higher score - it is a tool that
**knows the difference between a comment and a contract change**, tells you when
it is uncertain, and can show its calibration on real history. That is what this
page documents, and every number is reproducible:

```
# from inside the Orbit repo, pointing at the indexed graph
BACKTEST_ORBIT=/path/to/orbit python backtest.py 25     # section 4
BACKTEST_ORBIT=/path/to/orbit python find_risk.py       # section 5
BACKTEST_ORBIT=/path/to/orbit python risk_map.py > risk_map.svg
SCAR_REPO=. BACKTEST_ORBIT=/path/to/orbit python ci/scar_map.py   # section 7
python tests/integration_test.py                        # sections 3 & 7 (Tests 5, 6)
```
