#!/usr/bin/env python3
"""
Repo risk map: an SVG of the codebase's most load-bearing production functions,
coloured by test coverage (red = no test directly exercises it).

One picture of "where this codebase is fragile." Emitted as an SVG artifact.

    BACKTEST_ORBIT=/path/to/orbit.exe python risk_map.py > risk_map.svg
"""

import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "shared"))
from orbit_real_client import RealOrbitClient, _to_int   # noqa: E402

_TEST_LIKE = (
    "(lower({c}) LIKE '%/tests/%' OR lower({c}) LIKE '%/test/%' "
    "OR lower({c}) LIKE '%integration-tests%' OR lower({c}) LIKE '%testkit%' "
    "OR lower({c}) LIKE '%testutil%' OR lower({c}) LIKE '%/spec%' "
    "OR lower({c}) LIKE '%/fixtures/%' OR lower({c}) LIKE '%/fuzz/%' "
    "OR lower({c}) LIKE '%/benches/%' OR lower({c}) LIKE '%/examples/%')"
)
_GEN_LIKE = (
    "(lower({c}) LIKE '%.pb.go' OR lower({c}) LIKE '%.pb.rs' "
    "OR lower({c}) LIKE '%_pb2.py' OR lower({c}) LIKE '%generated%' "
    "OR lower({c}) LIKE '%/gen/%' OR lower({c}) LIKE '%.gen.%')"
)


def top_functions(client, limit=18):
    ct = _TEST_LIKE.format(c="sd.file_path")
    tt = _TEST_LIKE.format(c="d.file_path")
    tg = _GEN_LIKE.format(c="d.file_path")
    sql = f"""
SELECT d.name AS name, d.file_path AS file_path,
       COUNT(DISTINCT e.source_id) AS total,
       COUNT(DISTINCT CASE WHEN {ct} THEN e.source_id END) AS test
FROM gl_definition d
JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
JOIN gl_definition sd ON sd.id = e.source_id
WHERE d.definition_type = 'Function' AND NOT {tt} AND NOT {tg}
GROUP BY d.id, d.name, d.file_path
HAVING COUNT(DISTINCT e.source_id) >= 6
ORDER BY total DESC
LIMIT {limit};
"""
    out = []
    for r in client.query_raw(sql):
        total = _to_int(r.get("total"))
        test = _to_int(r.get("test"))
        out.append((r.get("name") or "?", total, test, test == 0))
    return out


def render_svg(funcs):
    W, rowh, pad_l, pad_t = 860, 30, 230, 70
    H = pad_t + rowh * len(funcs) + 40
    maxv = max((f[1] for f in funcs), default=1)
    bar_w = W - pad_l - 60
    untested = sum(1 for f in funcs if f[3])

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Segoe UI,Arial,sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="#0d1117"/>')
    s.append(f'<text x="20" y="30" fill="#e6edf3" font-size="20" font-weight="700">Constellation - Repo Risk Map</text>')
    s.append(f'<text x="20" y="52" fill="#8b949e" font-size="13">Most-called production functions - bar = fan-in - '
             f'<tspan fill="#f85149">red = no test directly exercises it</tspan> '
             f'({untested} of {len(funcs)} untested)</text>')
    for i, (name, total, test, frag) in enumerate(funcs):
        y = pad_t + i * rowh
        w = max(4, int(bar_w * total / maxv))
        color = "#f85149" if frag else "#3fb950"
        nm = html.escape(name[:30])
        s.append(f'<text x="{pad_l - 10}" y="{y + 19}" fill="#c9d1d9" font-size="13" text-anchor="end">{nm}</text>')
        s.append(f'<rect x="{pad_l}" y="{y + 6}" width="{w}" height="16" rx="3" fill="{color}" opacity="0.9"/>')
        lbl = f'{total} callers' + ('  - 0 tests' if frag else f'  - {test} tests')
        s.append(f'<text x="{pad_l + w + 8}" y="{y + 19}" fill="#8b949e" font-size="12">{lbl}</text>')
    s.append('</svg>')
    return "\n".join(s)


def main():
    client = RealOrbitClient(orbit_binary_path=os.environ.get("BACKTEST_ORBIT", "orbit"))
    if not client.health_check():
        print("ERROR: Orbit not available", file=sys.stderr)
        return 2
    funcs = top_functions(client)
    sys.stdout.write(render_svg(funcs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
