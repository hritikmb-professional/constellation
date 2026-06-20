#!/usr/bin/env python3
"""
Backtest: replay Constellation over a repo's recent merged history.

For each recent mainline commit (first-parent = one merged MR), we reconstruct
what that change did and what verdict Constellation would have posted, then
report the calibration: how many merges would have auto-approved vs needed
review vs been blocked - and surface the most interesting catch.

Run it FROM the target repo (so git sees its history), pointing at the Orbit
binary that owns the indexed graph:

    cd /path/to/repo-with-history
    BACKTEST_ORBIT=/path/to/orbit.exe python /path/to/constellation/backtest.py 40

Honesty: the edit CLASSIFICATION (cosmetic / contract-break) is exact per commit
(read from that commit's own content). Blast radius is measured against the
CURRENTLY-indexed graph, so it reflects each symbol's centrality today.
"""

import os
import re
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("shared", "agents/impact", "agents/provenance", "agents/ownership",
            "agents/compliance", "orchestrator", "ci"):
    sys.path.insert(0, os.path.join(HERE, sub))

from orbit_real_client import RealOrbitClient   # noqa: E402
from orchestrator import Orchestrator           # noqa: E402
from edit_semantics import classify_changes      # noqa: E402

SELF = ("constellation/",)


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def _not_self(f: str) -> bool:
    p = f.replace("\\", "/").lstrip("./")
    return not any(p.startswith(s) for s in SELF)


def mainline_commits(n: int):
    out = git("log", "--first-parent", "-n", str(n + 30), "--format=%H\x1f%s")
    rows = []
    for line in out.splitlines():
        if "\x1f" in line:
            sha, subject = line.split("\x1f", 1)
            rows.append((sha, subject))
    return rows


def changed_files(base, head):
    out = git("diff", "--name-only", base, head)
    return [f.strip() for f in out.splitlines() if f.strip() and _not_self(f.strip())]


def _function_spans(content):
    """[(name, start_line, end_line)] via regex + brace matching (C-like langs)."""
    spans = []
    for m in re.finditer(r"\b(?:fn|def|function)\s+([A-Za-z_]\w*)\s*[(<]", content):
        b = content.find("{", m.end())
        if b == -1:
            continue
        depth, i, n = 0, b, len(content)
        while i < n:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans.append((m.group(1),
                      content.count("\n", 0, m.start()) + 1,
                      content.count("\n", 0, i) + 1))
    return spans


def _changed_new_lines(base, head, f):
    diff = git("diff", "--unified=0", "--no-color", base, head, "--", f)
    lines = set()
    for L in diff.splitlines():
        if L.startswith("@@"):
            mm = re.search(r"\+(\d+)(?:,(\d+))?", L)
            if mm:
                s = int(mm.group(1))
                c = int(mm.group(2) or "1")
                lines.update(range(s, s + max(c, 1)))
    return lines


def changed_functions(base, head, files):
    names = set()
    for f in files:
        new = git("show", f"{head}:{f}")
        if not new:
            continue
        spans = _function_spans(new)
        if not spans:
            continue
        cl = _changed_new_lines(base, head, f)
        for name, s, e in spans:
            if any(s <= ln <= e for ln in cl):
                names.add(name)
    return sorted(names)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    orbit_bin = os.environ.get("BACKTEST_ORBIT", "orbit")
    client = RealOrbitClient(orbit_binary_path=orbit_bin)
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2
    orch = Orchestrator(client, gitlab_client=None)   # reused -> PageRank caches

    tally = {"AUTO_APPROVE": 0, "REVIEW_REQUIRED": 0, "SENIOR_REVIEW": 0, "BLOCK": 0}
    classes = {"cosmetic": 0, "body-edit": 0, "contract-break": 0, "unknown": 0}
    catches = []
    analyzed = 0

    print(f"Replaying up to {n} merged changes ...\n")
    for sha, subject in mainline_commits(n):
        if analyzed >= n:
            break
        base = sha + "^"
        files = changed_files(base, sha)
        if not files:
            continue   # our own vendored commits / empty
        names = changed_functions(base, sha, files)
        if not names:
            continue   # no function-level change we can attribute
        try:
            edit = classify_changes(base, names, head=sha)
            event = {
                "event_id": sha[:8], "event_type": "mr_opened",
                "payload": {"mr_id": sha[:8], "changed_symbols": names,
                            "mr_title": subject, "edit_semantics": edit},
            }
            v = orch.handle_event(event)
        except Exception as e:
            continue
        analyzed += 1
        tally[v.recommended_action] = tally.get(v.recommended_action, 0) + 1
        classes[edit["edit_class"]] = classes.get(edit["edit_class"], 0) + 1
        deps = (v.impact_verdict or {}).get("total_dependents", 0)
        if v.recommended_action in ("BLOCK", "SENIOR_REVIEW") or edit["edit_class"] == "contract-break":
            catches.append((sha[:8], subject[:60], v.recommended_action,
                            edit["edit_class"], deps, edit.get("contract_break_symbols", [])))

    print("=" * 70)
    print(f"CONSTELLATION BACKTEST - {analyzed} merged changes replayed")
    print("=" * 70)
    print("\nVerdict distribution:")
    for k in ("AUTO_APPROVE", "REVIEW_REQUIRED", "SENIOR_REVIEW", "BLOCK"):
        c = tally.get(k, 0)
        pct = (100 * c / analyzed) if analyzed else 0
        print(f"  {k:16} {c:3}  ({pct:4.0f}%)")
    print("\nEdit class distribution (exact, per-commit content):")
    for k in ("cosmetic", "body-edit", "contract-break"):
        c = classes.get(k, 0)
        pct = (100 * c / analyzed) if analyzed else 0
        print(f"  {k:16} {c:3}  ({pct:4.0f}%)")

    auto = tally.get("AUTO_APPROVE", 0)
    flagged = analyzed - auto
    print(f"\nHeadline: Constellation would AUTO-APPROVE {auto}/{analyzed} "
          f"({100*auto/analyzed if analyzed else 0:.0f}%) and route {flagged} for review.")

    if catches:
        print("\nMost interesting catches (contract changes / escalations):")
        for sha, subj, action, cls, deps, cb in sorted(catches, key=lambda r: -r[4])[:6]:
            cbs = (", ".join(cb)) if cb else "-"
            print(f"  [{sha}] {action:13} {cls:14} deps={deps:<4} {subj}")
            if cb:
                print(f"            contract changed: {cbs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
