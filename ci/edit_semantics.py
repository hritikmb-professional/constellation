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


def _signature_text(content: str, name: str):
    """
    The raw signature text of a function by NAME (name..matching close paren +
    return type), spanning a possibly multi-line param list. None if not found.
    """
    m = re.search(r"\b(?:fn|def|function)\s+" + re.escape(name) + r"\s*[(<]", content)
    if not m:
        return None
    open_idx = content.find("(", m.start())
    if open_idx == -1:
        return None
    depth, j = 0, open_idx
    while j < len(content):
        c = content[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    sig = content[m.start():j + 1]
    tail = content[j + 1:j + 200].split("{")[0].split(":")[0].split(";")[0]
    return sig + tail


def _norm(s):
    return re.sub(r"\s+", "", s) if s is not None else None


def _readable(s):
    return re.sub(r"\s+", " ", s).strip() if s is not None else None


def _extract_signature(content: str, name: str):
    """Whitespace-normalized signature for equality comparison (None if absent)."""
    return _norm(_signature_text(content, name))


def _contract_break_symbols(base: str, head: str, files: List[str], names: List[str]):
    """
    Names whose SIGNATURE changed or which were deleted, plus readable before/after
    signatures for the summary. Checked by name against old vs new file content
    (robust to multi-line signatures a line-based diff scan would miss).
    Returns (broken_set, {name: {"before","after"}}).
    """
    broken: Set[str] = set()
    sigs: Dict[str, Dict[str, str]] = {}
    if not names:
        return broken, sigs
    for f in files:
        old = _run(["git", "show", f"{base}:{f}"])
        new = _run(["git", "show", f"{head}:{f}"])
        for name in names:
            ot, nt = _signature_text(old, name), _signature_text(new, name)
            if ot is None and nt is None:
                continue
            if ot is not None and (nt is None or _norm(ot) != _norm(nt)):
                broken.add(name)
                sigs[name] = {"before": _readable(ot) or "(removed)",
                              "after": _readable(nt) or "(deleted)"}
    return broken, sigs


def classify_changes(base_sha: str, changed_symbols: List[str] = None, head: str = "HEAD") -> Dict[str, Any]:
    """
    Classify the MR's edit into {edit_class, edit_danger, contract_break_symbols, note}.

    edit_danger multiplies the topology risk; default 1.0 (no gating) only when
    we cannot read the diff, so behavior is never *silently* weakened.
    """
    changed_symbols = changed_symbols or []
    files = _changed_files(base_sha, head)
    if not files:
        return {
            "edit_class": "unknown",
            "edit_danger": 1.0,
            "contract_break_symbols": [],
            "note": "could not resolve the diff; risk not gated",
        }

    broken, signatures = _contract_break_symbols(base_sha, head, files, changed_symbols)
    if broken:
        return {
            "edit_class": "contract-break",
            "edit_danger": 1.0,
            "contract_break_symbols": sorted(broken),
            "signatures": signatures,
            "files": files,
            "note": f"signature/contract changed: {', '.join(sorted(broken))} — callers may break",
        }

    if all(_file_is_cosmetic(base_sha, head, f) for f in files):
        return {
            "edit_class": "cosmetic",
            "edit_danger": 0.0,
            "contract_break_symbols": [],
            "signatures": {},
            "files": files,
            "note": "only comments/whitespace changed — no behavior observable by dependents",
        }

    return {
        "edit_class": "body-edit",
        "edit_danger": 0.5,
        "contract_break_symbols": [],
        "signatures": {},
        "files": files,
        "note": "internal logic changed; signature/contract intact (behavioral effect is advisory)",
    }


if __name__ == "__main__":
    import sys, json
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    print(json.dumps(classify_changes(base), indent=2))
