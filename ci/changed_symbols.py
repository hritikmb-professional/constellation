#!/usr/bin/env python3
"""
Extract the changed code symbols of a merge request from its diff.

This is the piece that makes CI real: instead of being handed symbol names,
we compute them from the MR's actual diff. We parse the unified diff to find
which lines changed in each file, then ask Orbit which definitions span those
lines (`gl_definition.start_line..end_line`). The result is the set of real
functions/classes the MR touched — exactly what the Impact lens needs.

A regex fallback (definition headers in the diff) is used when Orbit can't map
a change (e.g. a brand-new file not yet in the index).
"""

import re
import subprocess
from typing import Dict, Set, List


# When Constellation is vendored INTO a host repo (e.g. constellation/ inside a
# fork), its own files must never be analyzed as "changed code" — they're the
# tool, not the codebase under review. Skip anything under these prefixes.
_SELF_PREFIXES = ("constellation/",)


def _is_self(path: str) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    return any(p.startswith(pre) for pre in _SELF_PREFIXES)


def _run(cmd: List[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def changed_lines_by_file(base_sha: str, head: str = "HEAD") -> Dict[str, Set[int]]:
    """Parse `git diff` into {file_path: {changed line numbers in the new version}}."""
    diff = _run(["git", "diff", "--unified=0", "--no-color", base_sha, head])
    files: Dict[str, Set[int]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            if _is_self(current):
                current = None   # skip the tool's own vendored files
                continue
            files.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            # @@ -a,b +c,d @@  -> new-side starts at c, spans d lines
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or "1")
                for ln in range(start, start + max(count, 1)):
                    files[current].add(ln)
    return {f: ls for f, ls in files.items() if ls}


def _orbit_symbols(client, file_path: str, lo: int, hi: int) -> Set[str]:
    """Definitions in `file_path` whose line span intersects [lo, hi]."""
    # Normalize to forward slashes and match on the exact path, or on the full
    # relative-path SUFFIX (handles Orbit storing a different root prefix). We
    # match the whole relative path — never just the basename — so a change to
    # one `helpers.rs` doesn't pull in symbols from other files of that name.
    base = file_path.replace("\\", "/").lstrip("./").replace("'", "''")
    sql = f"""
SELECT DISTINCT d.name
FROM gl_definition d
WHERE (REPLACE(d.file_path, '\\', '/') = '{base}'
       OR REPLACE(d.file_path, '\\', '/') LIKE '%/{base}')
  AND d.start_line <= {hi}
  AND d.end_line >= {lo}
  AND d.name IS NOT NULL;
"""
    try:
        rows = client.query_raw(sql)
    except Exception:
        return set()
    return {r.get("name") for r in rows if r.get("name")}


# function/class/struct/impl headers, as a fallback for unindexed changes
_DEF_RE = re.compile(
    r"^\+\s*(?:pub\s+|async\s+|export\s+|public\s+|private\s+)*"
    r"(?:fn|def|function|class|struct|impl|interface|trait)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _regex_fallback(base_sha: str, head: str = "HEAD") -> Set[str]:
    diff = _run(["git", "diff", "--no-color", base_sha, head])
    names: Set[str] = set()
    for line in diff.splitlines():
        m = _DEF_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def changed_symbols(client, base_sha: str, head: str = "HEAD") -> List[str]:
    """Return the sorted set of real symbols the MR changed."""
    by_file = changed_lines_by_file(base_sha, head)
    names: Set[str] = set()
    for fp, lines in by_file.items():
        lo, hi = min(lines), max(lines)
        names |= _orbit_symbols(client, fp, lo, hi)
    if not names:
        # Nothing mapped via the graph (e.g. new files) — fall back to the diff.
        names = _regex_fallback(base_sha, head)
    return sorted(names)


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
    from orbit_real_client import RealOrbitClient

    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    c = RealOrbitClient(orbit_binary_path=os.environ.get("ORBIT_BIN", "orbit"))
    print(changed_symbols(c, base))
