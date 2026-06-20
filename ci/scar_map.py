#!/usr/bin/env python3
"""
Scar map: a history-grounded change-failure prior, with receipts.

Constellation's structural risk answers "how central is the code you touched."
This adds the orthogonal question history can answer: "has code *near* your
change been a source of trouble before?" We mine git for the high-signal scars -
reverts, hotfix/rollback/emergency commits, and bug-fix density - per file, then
walk the call graph one hop out from the changed symbols and aggregate a
proximity-weighted prior over the neighborhood's scars.

Crucially this is NOT a calibrated probability or a learned model. It is a
transparent, bounded prior where every point of added risk cites the exact
commit (revert/hotfix SHA) that justifies it. The framing - and the cap - keep
it honest: it nudges the verdict toward a human when you are editing next to
historically fragile code, and it shows its receipts.

    # standalone scan (run from a repo with full history; point at its Orbit graph)
    BACKTEST_ORBIT=/path/to/orbit python ci/scar_map.py [window]

Wired into CI via run_ci.py -> payload['scar_analysis']; the Impact agent folds
the (capped) prior into change_failure_rate. When no scar analysis is supplied
(e.g. the backtest), the prior is 0 and behaviour is unchanged.
"""

import os
import re
import subprocess
import sys
from typing import Dict, List, Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "shared"))
from orbit_real_client import RealOrbitClient   # noqa: E402

# --- tuning constants (all explicit so the number is reproducible) ----------
WINDOW = 4000              # commits of history to mine (bounds runtime)
MAX_FILES_PER_COMMIT = 50  # skip bulk reformat/rename/move commits (noise)
MIN_SUPPORT = 4            # need >= this many commits before fix-density counts
PRIOR_CAP = 0.12           # the scar prior can never add more than this much risk
PRIOR_SCALE = 0.10         # weighted-intensity -> risk, before the cap
# proximity weights: the changed file itself counts full; one hop out, half.
W_CHANGED, W_CALLER, W_CALLEE = 1.0, 0.5, 0.5

# A real `git revert` writes the subject `Revert "<original>"`. Very reliable.
_REVERT_RE = re.compile(r'^\s*revert[\s:"]', re.I)
# Emergency-change vocabulary (reverts handled separately above).
_HOTFIX_RE = re.compile(r'\b(hotfix|roll ?back|emergency|incident|sev[-\s]?\d)\b', re.I)
# Bug-fix signal - deliberately broad, then de-noised by the exclude list.
_FIX_RE = re.compile(r'\b(fix|fixe[sd]|bug|bugfix|regress\w*|broke[n]?|crash)\b', re.I)
# Cosmetic / housekeeping "fixes" that are not change-failure signal.
_FIX_EXCLUDE = (
    "typo", "lint", "rustfmt", "gofmt", "clippy", "format", "fmt",
    "whitespace", "comment", "spelling", "changelog", "readme",
    "doc ", "docs", "rename", "clean up", "cleanup", "warning",
)
_LOCKFILES = (
    "cargo.lock", "package-lock.json", "yarn.lock", "go.sum",
    "pnpm-lock.yaml", "poetry.lock", "gemfile.lock", "composer.lock",
)


class Scar:
    __slots__ = ("file", "reverts", "hotfixes", "fixes", "total", "receipts")

    def __init__(self, file: str):
        self.file = file
        self.reverts = 0
        self.hotfixes = 0
        self.fixes = 0
        self.total = 0
        self.receipts: List[Dict[str, str]] = []   # the SHAs that justify the score

    @property
    def fix_density(self) -> float:
        return self.fixes / self.total if self.total else 0.0

    def intensity(self) -> float:
        """
        A 0..1 per-file scar intensity. Reverts dominate (most reliable); the
        bug-fix signal only counts once a file has enough history (MIN_SUPPORT)
        so a single 'fix' on a one-commit file is not read as 100% fragile, and
        it rewards both fix DENSITY and fix VOLUME so a repeatedly-patched file
        outranks one fixed once.
        """
        density_term = volume_term = 0.0
        if self.total >= MIN_SUPPORT:
            density_term = 0.30 * min(self.fix_density, 0.6)   # up to 0.18
            volume_term = 0.05 * min(self.fixes, 6)            # up to 0.30
        return min(1.0, 0.40 * self.reverts + 0.22 * self.hotfixes + density_term + volume_term)

    def has_signal(self) -> bool:
        return self.reverts or self.hotfixes or self.fixes


def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, errors="replace"
    ).stdout


def _is_noise_file(client, path: str) -> bool:
    base = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base in _LOCKFILES or client._is_generated_path(path)


def mine_scars(client, repo: str = ".", window: int = WINDOW) -> Dict[str, Scar]:
    """
    One pass over git history -> {file_path: Scar}.

    Each commit is classified once (revert / hotfix / fix) from its subject and
    attributed to every (non-noise) file it touched. Bulk commits that touch
    more than MAX_FILES_PER_COMMIT files are skipped as reformat/rename noise.
    """
    # NUL-prefixed header per commit, then --name-only file lines beneath it.
    out = _git(
        repo, "log", "--no-merges", "-n", str(window),
        "--name-only", "--date=short",
        "--format=%x00%H%x1f%ad%x1f%s",
    )
    scars: Dict[str, Scar] = {}
    sha = date = subj = None
    files: List[str] = []

    def flush():
        if sha is None:
            return
        if not files or len(files) > MAX_FILES_PER_COMMIT:
            return
        sl = subj.lower()
        is_revert = bool(_REVERT_RE.match(sl))
        is_hotfix = (not is_revert) and bool(_HOTFIX_RE.search(sl))
        is_fix = (
            (not is_revert) and (not is_hotfix)
            and bool(_FIX_RE.search(sl))
            and not any(x in sl for x in _FIX_EXCLUDE)
        )
        kind = "revert" if is_revert else "hotfix" if is_hotfix else "fix" if is_fix else None
        for f in files:
            if _is_noise_file(client, f):
                continue
            s = scars.get(f)
            if s is None:
                s = scars[f] = Scar(f)
            s.total += 1
            if kind == "revert":
                s.reverts += 1
            elif kind == "hotfix":
                s.hotfixes += 1
            elif kind == "fix":
                s.fixes += 1
            # Keep a few receipts per file (the literal commits that justify the
            # score); reverts/hotfixes are prioritized over plain fixes at display.
            if kind and len(s.receipts) < 5:
                s.receipts.append({"sha": sha[:10], "date": date, "subject": subj[:80], "kind": kind})

    for line in out.split("\n"):
        if line.startswith("\x00"):
            flush()
            parts = line[1:].split("\x1f")
            sha = parts[0] if len(parts) > 0 else ""
            date = parts[1] if len(parts) > 1 else ""
            subj = parts[2] if len(parts) > 2 else ""
            files = []
        elif line.strip():
            files.append(line.strip())
    flush()
    return scars


def _neighborhood(client, symbols: List[str]) -> Dict[str, float]:
    """
    Files within one call-graph hop of the changed symbols, with a proximity
    weight: the changed file(s) = 1.0, direct callers / callees = 0.5.
    """
    weights: Dict[str, float] = {}

    def add(path: str, w: float):
        if not path:
            return
        p = path.replace("\\", "/")
        weights[p] = max(weights.get(p, 0.0), w)

    qs = RealOrbitClient._quote_symbols(symbols)

    # 0-hop: the files the changed symbols live in.
    for r in client.query_raw(
        f"SELECT DISTINCT file_path FROM gl_definition WHERE name IN ({qs});"
    ):
        add(r.get("file_path"), W_CHANGED)

    # 1-hop callers (who calls the changed symbols).
    try:
        for c in client.query("direct_callers", symbols=symbols).get("callers", []):
            add(c.get("file_path"), W_CALLER)
    except Exception:
        pass

    # 1-hop callees (what the changed symbols call).
    for r in client.query_raw(f"""
SELECT DISTINCT t.file_path AS file_path
FROM gl_definition s
JOIN gl_edge e ON e.source_id = s.id AND e.relationship_kind = 'CALLS'
JOIN gl_definition t ON t.id = e.target_id
WHERE s.name IN ({qs});"""):
        add(r.get("file_path"), W_CALLEE)

    return weights


_RECEIPT_RANK = {"revert": 0, "hotfix": 1, "fix": 2}


def _best_receipts(receipts: List[Dict[str, str]], n: int = 3) -> List[Dict[str, str]]:
    """Strongest receipts first: reverts, then hotfixes, then fixes."""
    return sorted(receipts, key=lambda r: _RECEIPT_RANK.get(r.get("kind"), 9))[:n]


def _proximity_label(w: float) -> str:
    if w >= W_CHANGED:
        return "changed file"
    return "1 hop away"


def compute_scar_prior(client, symbols: List[str], repo: str = ".",
                       window: int = WINDOW) -> Dict[str, Any]:
    """
    The MR-time prior: proximity-weighted scar intensity over the change's
    call-graph neighborhood, capped, with the receipts that justify it.
    """
    if not symbols:
        return {"prior": 0.0, "contributors": [], "window": window, "neighborhood_files": 0}

    scars = mine_scars(client, repo=repo, window=window)
    neigh = _neighborhood(client, symbols)

    weighted = 0.0
    contributors = []
    for path, w in neigh.items():
        s = scars.get(path)
        if not s or not s.has_signal():
            continue
        inten = s.intensity()
        if inten <= 0:           # below the support floor -> no usable signal
            continue
        contribution = w * inten
        weighted += contribution
        contributors.append({
            "file": path,
            "proximity": _proximity_label(w),
            "weight": w,
            "reverts": s.reverts,
            "hotfixes": s.hotfixes,
            "fix_density": round(s.fix_density, 2),
            "intensity": round(inten, 2),
            "contribution": round(contribution, 3),
            "receipts": _best_receipts(s.receipts),
        })

    contributors.sort(key=lambda c: -c["contribution"])
    prior = min(PRIOR_CAP, PRIOR_SCALE * weighted)
    return {
        "prior": round(prior, 3),
        "capped": prior >= PRIOR_CAP,
        "window": window,
        "neighborhood_files": len(neigh),
        "contributors": contributors,
        "note": "history-grounded prior with receipts; a bounded nudge, not a calibrated probability",
    }


def _main() -> int:
    window = int(sys.argv[1]) if len(sys.argv) > 1 else WINDOW
    repo = os.environ.get("SCAR_REPO", ".")
    client = RealOrbitClient(orbit_binary_path=os.environ.get("BACKTEST_ORBIT", "orbit"))
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2

    scars = mine_scars(client, repo=repo, window=window)
    ranked = sorted(
        (s for s in scars.values()
         if s.has_signal() and not client._is_test_path(s.file)),
        key=lambda s: (-s.intensity(), -s.reverts, -s.hotfixes),
    )

    print("=" * 78)
    print(f"CONSTELLATION - scar map (last {window} commits of real git history)")
    print("=" * 78)
    print("\nProduction files most marked by past trouble (reverts / hotfixes / fix-density):\n")
    for s in ranked[:15]:
        print(f"  {s.intensity():.2f}  rev={s.reverts} hf={s.hotfixes} "
              f"fixes={s.fixes}/{s.total} ({s.fix_density:.0%})  {s.file}")
    if ranked:
        top = ranked[0]
        print("\n" + "-" * 78)
        print(f"Sharpest scar: {top.file}")
        for r in _best_receipts(top.receipts):
            print(f"  [{r['kind']:6}] {r['sha']}  {r['date']}  {r['subject']}")
        print("\n(These SHAs are the receipts - the literal commits that fixed/reverted this file.)")
    else:
        print("  (no scars found in this window)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
