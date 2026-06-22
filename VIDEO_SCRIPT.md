# Constellation — 3-minute demo video script

A shot-by-shot you can record. Target **3:00**. The whole video is built around ONE
reveal (same function, opposite verdict) and then proof that it's real. Record at
1080p, narrate calmly, let the screen do the work. Times are cumulative.

> **Golden rule:** show, don't claim. Every number on screen should be one a judge
> could reproduce. The honesty *is* the pitch.

---

## 0:00 - 0:20 · The hook (talking head or voiceover over title card)

> "Every code-review tool tells you *where* a change is. None of them tell you what
> it *means*. This is Constellation - it runs on GitLab Orbit's knowledge graph and
> answers the question a senior engineer asks in two seconds: if I merge this, what
> breaks, who owns it, and has it hurt us before?"

**On screen:** title card - "Constellation · graph-native merge-request intelligence on GitLab Orbit."

## 0:20 - 1:05 · The reveal (the whole pitch in one beat)

Split screen or two MRs side by side on the same function, `compile` (509 dependents).

- **Left MR:** a one-line **comment** added to `compile`. Show the posted Constellation comment → **AUTO_APPROVE**.
- **Right MR:** a **signature change** to the *same* `compile`. Show the comment → **BLOCK**.

> "Same function. Five hundred and nine things depend on it - either way. A linter,
> CODEOWNERS, SonarQube - they all see the same file, the same 509. Constellation
> sees the difference: a comment can't break a caller, a signature change can. Risk
> is *what* you changed, not just *where*."

**On screen:** highlight "AUTO_APPROVE" vs "BLOCK", and the line "509 transitive dependents" present in both.

## 1:05 - 1:35 · Under the hood (why the verdict is real)

Scroll the BLOCK verdict comment slowly.

> "This isn't a template. The blast radius is a real recursive traversal of the
> call graph. It flags `compile` as a keystone and a chokepoint - a cut vertex
> whose failure isolates downstream code. It lists the actual callers to review,
> with file and line. All of it queried live from the Orbit graph."

**On screen:** the mermaid blast-radius diagram (chokepoints in red), the "callers to review" checklist, the test-vs-production split.

## 1:35 - 2:05 · The two history lenses (the new depth)

Show the **scar prior** block, then the **ownership** block.

> "It also reads history. This file has been patched repeatedly - here are the exact
> fix commits as receipts - so the change-failure risk gets a small, *bounded* nudge.
> And it runs real git-blame over the blast radius: this load-bearing code has a bus
> factor of one - if this author is out, nobody else knows it. Authors are anonymized
> by default - we never name a person as a single point of failure in a public comment."

**On screen:** scar receipts (SHAs), then "Author A - 77%, SPOF" block.

## 2:05 - 2:35 · Proof it's calibrated (not a toy)

Show the backtest output and the risk map SVG.

> "We replayed the last 25 merged MRs. Constellation would have auto-approved 60% of
> them and blocked one - an MR that changed eight signatures at once, touching over a
> thousand dependents. And scanning the repo: of the 18 most-called production
> functions, twelve have no direct test. It even reviews its own merge requests."

**On screen:** backtest verdict distribution; the red/green risk-map bar chart.

## 2:35 - 2:55 · Honesty (the closer that wins trust)

> "We're deliberate about what's real. The lineage and approval data need GitLab's
> SDLC tables, so those are labelled representative. The call graph is static, so we
> say 'no *direct* test', not 'untested'. A review tool that over-claims gets routed
> around - so this one doesn't."

**On screen:** the "what we're honest about" section, or the HONESTY.md page.

## 2:55 - 3:00 · Close

> "Constellation. It runs in CI today, and it can block a bad merge before a human
> ever sees it."

**On screen:** the Decision Gate line + the GitLab MR with the posted comment.

---

## Capture checklist (record these before editing)

- [ ] Two real MRs on `compile` (or any keystone): one comment edit, one signature edit, with the posted Constellation comments visible. **This is the money shot - get it clean.**
- [ ] A full BLOCK verdict comment scrolled top-to-bottom (summary → mermaid → callers → impact → scar → ownership).
- [ ] Terminal: `python backtest.py 25` output.
- [ ] `risk_map.svg` open in a browser.
- [ ] Terminal: `python ci/scar_map.py` and `python ci/git_ownership.py compile` (anonymized).
- [ ] The GitLab pipeline showing the Constellation job (green, with "Posted verdict to MR" in the log) - doubles as your live-deployment proof.

## Tips

- Pre-stage the two MRs so you're not waiting on CI on camera; cut to the posted comment.
- Keep narration under the times above - silence while scrolling reads as confidence.
- End on the GitLab MR, not a slide - the last thing the judge sees should be the real product.
