#!/usr/bin/env python3
"""
Edit-semantics: classify WHAT a merge request changed, not just where.

Constellation's blast radius answers "how much depends on this symbol." On its
own that makes a one-line comment on a central function score the same CRITICAL
as a full rewrite — a false positive that gets a hard gate muted on day one.

This module reads the diff and classifies the edit so risk can be GATED by it:

    cosmetic        only comments/whitespace changed  -> danger 0.0  (auto-approve)
    body-edit       internal logic changed, signature intact -> danger 0.5  (review)
    contract-break  a signature/param/return/public-deletion changed -> danger 1.0  (escalate)

`edit_danger` multiplies the topology signals (keystone, blast radius) before
they drive the verdict. So:
  - keystone touched by a comment        -> 0.90 * 0.0 = 0   -> AUTO-APPROVE
  - keystone whose signature changed     -> 0.90 * 1.0 = 0.90 -> BLOCK (with the broken callers)

HONEST SCOPE: the cosmetic and contract-break tiers are string/structural rules
(robust for single-line signatures); the body-edit middle is where an LLM would
label *how* behavior changed. Contract-break is the only class where "every
CALLS dependent is provably affected" is true — body-edits stay advisory.
"""

import os
import re
import subprocess
from typing import Dict, List, Set, Any

# Vendored tool code (when Constellation runs inside a host repo) is never the
# subject of analysis.
_SELF_PREFIXES = ("constellation/",)

# Signature headers we can compare as single lines, across the common langs.
_SIG_RE = re.compile(
    r"^([+-])\s*"
    r"((?:pub(?:\([^)]*\))?\s+|async\s+|unsafe\s+|const\s+|export\s+|public\s+|private\s+|static\s+|default\s+)*"
    r"(?:fn|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[(<].*)$"
)

_C_LIKE = {".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".js", ".jsx",
           ".ts", ".tsx", ".go", ".kt", ".swift", ".scala"}
_HASH_LIKE = {".py", ".rb", ".sh", ".pl"}


def _is_self(path: str) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    return any(p.startswith(pre) for pre in _SELF_PREFIXES)


def _run(cmd: List[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def _strip_comments_ws(text: str, ext: str) -> str:
    """Remove comments and all whitespace so only behavioral text remains."""
    if ext in _C_LIKE:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)   # block comments
        text = re.sub(r"//[^\n]*", "", text)                 # line comments
    elif ext in _HASH_LIKE:
        text = re.sub(r"#[^\n]*", "", text)
    return re.sub(r"\s+", "", text)


def _changed_files(base: str, head: str) -> List[str]:
    out = _run(["git", "diff", "--name-only", base, head])
    return [f.strip() for f in out.splitlines() if f.strip() and not _is_self(f.strip())]


def _file_is_cosmetic(base: str, head: str, path: str) -> bool:
    """True if the file's behavioral text (comments+whitespace stripped) is unchanged."""
    ext = os.path.splitext(path)[1].lower()
    old = _run(["git", "show", f"{base}:{path}"])
    new = _run(["git", "show", f"{head}:{path}"])
    if not old and not new:
        return False
    return _strip_comments_ws(old, ext) == _strip_comments_ws(new, ext)


def _contract_break_symbols(base: str, head: str) -> Set[str]:
    """Names whose single-line signature was changed or removed in the diff."""
    diff = _run(["git", "diff", "--no-color", base, head])
    old: Dict[str, str] = {}
    new: Dict[str, str] = {}
    for line in diff.splitlines():
        m = _SIG_RE.match(line)
        if not m:
            continue
        sign, sig_text, name = m.group(1), m.group(2).strip(), m.group(3)
        (old if sign == "-" else new)[name] = sig_text
    broken: Set[str] = set()
    for name, sig in old.items():
        if name not in new or new[name] != sig:   # removed, or signature changed
            broken.add(name)
    return broken


def classify_changes(base_sha: str, head: str = "HEAD") -> Dict[str, Any]:
    """
    Classify the MR's edit into {edit_class, edit_danger, contract_break_symbols, note}.

    edit_danger multiplies the topology risk; default 1.0 (no gating) only when
    we cannot read the diff, so behavior is never *silently* weakened.
    """
    files = _changed_files(base_sha, head)
    if not files:
        return {
            "edit_class": "unknown",
            "edit_danger": 1.0,
            "contract_break_symbols": [],
            "note": "could not resolve the diff; risk not gated",
        }

    broken = _contract_break_symbols(base_sha, head)
    if broken:
        return {
            "edit_class": "contract-break",
            "edit_danger": 1.0,
            "contract_break_symbols": sorted(broken),
            "note": f"signature/contract changed: {', '.join(sorted(broken))} — callers may break",
        }

    if all(_file_is_cosmetic(base_sha, head, f) for f in files):
        return {
            "edit_class": "cosmetic",
            "edit_danger": 0.0,
            "contract_break_symbols": [],
            "note": "only comments/whitespace changed — no behavior observable by dependents",
        }

    return {
        "edit_class": "body-edit",
        "edit_danger": 0.5,
        "contract_break_symbols": [],
        "note": "internal logic changed; signature/contract intact (behavioral effect is advisory)",
    }


if __name__ == "__main__":
    import sys, json
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    print(json.dumps(classify_changes(base), indent=2))
