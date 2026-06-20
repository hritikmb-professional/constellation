#!/usr/bin/env python3
"""
Real Orbit Client: Connects to actual Orbit Local database via SQL.

This client executes queries against a real Orbit Local instance.
Tested against Orbit Local v0.75.1 with DuckDB backend.
"""

import subprocess
import json
import logging
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _to_int(value, default: int = 0) -> int:
    """
    Robustly coerce an Orbit cell value to int.

    Orbit's table output renders SQL NULL (e.g. MAX(depth) over an empty set,
    when a changed symbol has no callers) as an empty string. int('') raises,
    so empty / None / non-numeric values fall back to `default`.
    """
    try:
        s = str(value).strip()
        return int(s) if s else default
    except (TypeError, ValueError):
        return default


class RealOrbitClient:
    """
    Execute queries against a real Orbit Local database.

    Interface: same as MockOrbitClient for seamless swapping.
    """

    def __init__(self, orbit_binary_path: str = "orbit", db_path: Optional[str] = None):
        """
        Initialize with path to Orbit binary and optional database path.

        Args:
            orbit_binary_path: Path to orbit.exe (or just "orbit" if in PATH)
            db_path: Path to Orbit database directory (optional, uses ~/.orbit/graph.duckdb by default)
        """
        self.orbit_binary = orbit_binary_path
        self.db_path = db_path
        self.available = self._check_orbit()

    def _check_orbit(self) -> bool:
        """Check if Orbit binary is available and working."""
        try:
            result = subprocess.run(
                [self.orbit_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info(f"Orbit Local available: {result.stdout.strip()}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        logger.error(f"Orbit binary not found: {self.orbit_binary}")
        return False

    def health_check(self) -> bool:
        """Check if database is indexed and queryable."""
        if not self.available:
            return False

        try:
            result = self.query_raw("SELECT COUNT(*) as count FROM gl_definition")
            return result is not None and len(result) > 0
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def query_raw(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute raw SQL against Orbit database.

        Returns list of rows as dicts.
        """
        if not self.available:
            raise RuntimeError("Orbit not available")

        try:
            # Build command
            cmd = [self.orbit_binary, "sql", sql]
            if self.db_path:
                cmd.extend(["--database", self.db_path])

            # Execute
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error(f"Query failed: {result.stderr}")
                return []

            # Parse output: orbit sql returns table format, convert to dicts
            rows = self._parse_orbit_output(result.stdout)
            return rows

        except subprocess.TimeoutExpired:
            logger.error(f"Query timeout: {sql[:100]}")
            return []
        except Exception as e:
            logger.error(f"Query error: {e}")
            return []

    def _parse_orbit_output(self, output: str) -> List[Dict[str, Any]]:
        """
        Parse orbit sql table output into list of dicts.

        Format:
        +---+-----+
        | id| name|
        +---+-----+
        | 1 | foo |
        +---+-----+
        """
        lines = output.strip().split("\n")
        if len(lines) < 3:
            return []

        # Extract column names from header (second line after first separator)
        header_line = lines[1] if len(lines) > 1 else ""
        columns = [col.strip() for col in header_line.split("|")[1:-1]]

        rows = []
        for line in lines[3:]:  # Skip header lines
            if line.startswith("+"):
                continue
            if not line.strip():
                continue

            values = [v.strip() for v in line.split("|")[1:-1]]
            if len(values) == len(columns):
                row = dict(zip(columns, values))
                rows.append(row)

        return rows

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a typed query (matches MockOrbitClient interface).

        Maps query_type to SQL query and returns structured result.
        """
        if query_type == "transitive_dependents":
            return self._query_transitive_dependents(kwargs)
        elif query_type == "affected_services":
            return self._query_affected_services(kwargs)
        elif query_type == "affected_owners":
            return self._query_affected_owners(kwargs)
        elif query_type == "ownership_centrality":
            return self._query_ownership_centrality(kwargs)
        elif query_type == "symbol_definition":
            return self._query_symbol_definition(kwargs)
        elif query_type == "subgraph_edges":
            return self._query_subgraph_edges(kwargs)
        elif query_type == "definitions_by_id":
            return self._query_definitions_by_id(kwargs)
        elif query_type == "all_call_edges":
            return self._query_all_call_edges(kwargs)
        elif query_type == "symbol_defs":
            return self._query_symbol_defs(kwargs)
        else:
            logger.warning(f"Unknown query type: {query_type}")
            return {}

    def _query_all_call_edges(self, params: Dict) -> Dict[str, Any]:
        """Return every CALLS edge (source_id, target_id) for global centrality."""
        rows = self.query_raw(
            "SELECT source_id, target_id FROM gl_edge WHERE relationship_kind = 'CALLS';"
        )
        edges = [
            (r.get("source_id"), r.get("target_id"))
            for r in rows
            if r.get("source_id") and r.get("target_id")
        ]
        return {"edges": edges}

    def _query_symbol_defs(self, params: Dict) -> Dict[str, Any]:
        """Resolve symbol names to their definitions (id, name, inbound-call count)."""
        symbols = params.get("symbols", [])
        if not symbols:
            return {"defs": []}
        name = self._quote_symbols(symbols)
        sql = f"""
SELECT d.id, d.name, COUNT(DISTINCT e.source_id) AS inbound
FROM gl_definition d
LEFT JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
WHERE d.name IN ({name})
GROUP BY d.id, d.name;
"""
        rows = self.query_raw(sql)
        return {
            "defs": [
                {"id": r.get("id"), "name": r.get("name"), "inbound": _to_int(r.get("inbound"))}
                for r in rows
            ]
        }

    def _query_subgraph_edges(self, params: Dict) -> Dict[str, Any]:
        """
        Return the induced CALLS edges of the blast-radius subgraph + the root ids.

        The closure (seeds + all transitive callers) is built with set semantics
        so it terminates on cycles; the induced edges are CALLS edges with both
        endpoints in the closure. Feeds the cut-vertex / chokepoint analysis.
        """
        symbols = params.get("symbols", [])
        if not symbols:
            return {"edges": [], "roots": []}
        symbol_list = self._quote_symbols(symbols)

        edge_sql = f"""
WITH RECURSIVE seeds AS (
  SELECT id FROM gl_definition WHERE name IN ({symbol_list})
),
closure AS (
  SELECT id FROM seeds
  UNION
  SELECT e.source_id
  FROM gl_edge e JOIN closure c ON e.target_id = c.id AND e.relationship_kind = 'CALLS'
)
SELECT e.source_id AS source_id, e.target_id AS target_id
FROM gl_edge e
JOIN closure a ON e.source_id = a.id
JOIN closure b ON e.target_id = b.id
WHERE e.relationship_kind = 'CALLS';
"""
        rows = self.query_raw(edge_sql)
        edges = [
            (r.get("source_id"), r.get("target_id"))
            for r in rows
            if r.get("source_id") and r.get("target_id")
        ]

        root_rows = self.query_raw(
            f"SELECT id FROM gl_definition WHERE name IN ({symbol_list});"
        )
        roots = [r.get("id") for r in root_rows if r.get("id")]
        return {"edges": edges, "roots": roots}

    def _query_definitions_by_id(self, params: Dict) -> Dict[str, Any]:
        """Resolve a set of definition ids to {id: {name, file_path}}."""
        ids = params.get("ids", [])
        # ids originate from the graph (numeric); keep only digit strings.
        safe = [str(i) for i in ids if str(i).isdigit()]
        if not safe:
            return {"definitions": {}}
        id_list = ", ".join(safe)
        rows = self.query_raw(
            f"SELECT id, name, file_path FROM gl_definition WHERE id IN ({id_list});"
        )
        return {
            "definitions": {
                r.get("id"): {"name": r.get("name"), "file_path": r.get("file_path")}
                for r in rows
            }
        }

    def _query_symbol_definition(self, params: Dict) -> Dict[str, Any]:
        """
        Resolve a symbol name to its REAL definition in the code graph.

        Returns the highest-inbound definition for the name with its actual
        file path, fully-qualified name, kind, line span, and caller count.
        This makes the finding -> symbol -> definition steps of a provenance
        lineage real (the MR -> author steps still need SDLC data at deploy).
        """
        symbol = params.get("symbol")
        if not symbol:
            return {}
        name = self._quote_symbols([symbol])
        sql = f"""
SELECT d.id, d.name, d.fqn, d.file_path, d.definition_type,
       d.start_line, d.end_line,
       COUNT(DISTINCT e.source_id) AS inbound
FROM gl_definition d
LEFT JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
WHERE d.name IN ({name})
GROUP BY d.id, d.name, d.fqn, d.file_path, d.definition_type, d.start_line, d.end_line
ORDER BY inbound DESC
LIMIT 1;
"""
        rows = self.query_raw(sql)
        if not rows:
            return {}
        r = rows[0]
        return {
            "definition": {
                "name": r.get("name"),
                "fqn": r.get("fqn"),
                "file_path": r.get("file_path"),
                "definition_type": r.get("definition_type"),
                "start_line": _to_int(r.get("start_line")),
                "end_line": _to_int(r.get("end_line")),
                "inbound_callers": _to_int(r.get("inbound")),
            }
        }

    # Maximum hops for transitive caller traversal. The Orbit call graph
    # terminates well before this in practice (the knowledge-graph repo's
    # deepest caller chain from allow_all/compile is 3), and the depth bound
    # guarantees termination on cyclic call graphs.
    MAX_TRANSITIVE_DEPTH = 8

    @staticmethod
    def _quote_symbols(symbols: List[str]) -> str:
        """
        Build a SQL IN-list from symbol names, escaping single quotes.

        Symbols originate from MR diffs (untrusted), so doubling `'` -> `''`
        is required both for correctness (names like O'Brien) and to remove
        the SQL-injection surface of naive interpolation.
        """
        return ", ".join("'" + str(s).replace("'", "''") + "'" for s in symbols)

    def _recursive_callers_cte(self, symbols: List[str]) -> str:
        """
        A CTE that materializes the transitive caller set `callers(id, depth)`.

        Walks `CALLS` edges backward from the changed symbols: depth 1 is the
        direct callers, depth 2 the callers of those, and so on. `UNION`
        (set semantics) plus the depth bound keeps it terminating and bounded.
        """
        symbol_list = self._quote_symbols(symbols)
        return f"""
WITH RECURSIVE seeds AS (
  SELECT id FROM gl_definition WHERE name IN ({symbol_list})
),
callers AS (
  SELECT e.source_id AS id, 1 AS depth
  FROM gl_edge e
  JOIN seeds s ON e.target_id = s.id AND e.relationship_kind = 'CALLS'
  UNION
  SELECT e.source_id AS id, c.depth + 1
  FROM gl_edge e
  JOIN callers c ON e.target_id = c.id AND e.relationship_kind = 'CALLS'
  WHERE c.depth < {self.MAX_TRANSITIVE_DEPTH}
)"""

    def _query_transitive_dependents(self, params: Dict) -> Dict[str, Any]:
        """Query the transitive dependents (multi-hop callers) of changed symbols."""
        symbols = params.get("symbols", [])
        if not symbols:
            return {"total_dependents": 0, "affected_services": 0, "max_depth": 0}

        sql = self._recursive_callers_cte(symbols) + """
SELECT
  COUNT(DISTINCT c.id) AS total_dependents,
  COUNT(DISTINCT d.project_id) AS affected_services,
  MAX(c.depth) AS max_depth
FROM callers c
JOIN gl_definition d ON d.id = c.id;
"""
        results = self.query_raw(sql)
        if results and len(results) > 0:
            r = results[0]
            return {
                "total_dependents": _to_int(r.get("total_dependents")),
                "affected_services": _to_int(r.get("affected_services")),
                "max_depth": _to_int(r.get("max_depth")),
            }
        return {"total_dependents": 0, "affected_services": 0, "max_depth": 0}

    @staticmethod
    def _module_of(file_path: str) -> str:
        """The owning code area: the first two path segments of a file."""
        parts = file_path.replace("\\", "/").split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]

    @staticmethod
    def _is_critical_path(file_path: str) -> bool:
        """Heuristic: files touching sensitive areas are on the critical path."""
        fp = file_path.lower()
        keywords = ["security", "auth", "redaction", "server", "payment", "billing"]
        return any(kw in fp for kw in keywords)

    def _query_affected_files(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Real per-file transitive blast radius: files containing transitive callers."""
        if not symbols:
            return []
        sql = self._recursive_callers_cte(symbols) + """
SELECT d.file_path AS file_path, COUNT(DISTINCT c.id) AS affected_defs
FROM callers c
JOIN gl_definition d ON d.id = c.id
GROUP BY d.file_path
ORDER BY affected_defs DESC;
"""
        return self.query_raw(sql)

    def _query_affected_services(self, params: Dict) -> Dict[str, Any]:
        """
        Real affected services, file-level. Since a local Orbit index is a
        single repo, the meaningful unit is the file/module carrying callers
        of the changed symbols. Shape matches MockOrbitClient for swap-in.
        """
        symbols = params.get("symbols", [])
        rows = self._query_affected_files(symbols)

        services = []
        for i, r in enumerate(rows):
            fp = r.get("file_path") or ""
            services.append(
                {
                    "project_id": f"f{i + 1}",
                    "project_name": self._module_of(fp),
                    "full_path": fp,
                    "affected_definitions": _to_int(r.get("affected_defs")),
                    "is_critical_path": self._is_critical_path(fp),
                }
            )
        return {"affected_services": services}

    def _query_affected_owners(self, params: Dict) -> Dict[str, Any]:
        """
        Real structural ownership, derived from the code graph.

        Orbit's schema has no git/author data, so we attribute the blast
        radius to code AREAS (modules/crates) rather than inventing people.
        At deploy time on real GitLab this is enriched with CODEOWNERS + git
        blame; locally it is an honest structural proxy.
        """
        symbols = params.get("symbols", [])
        rows = self._query_affected_files(symbols)

        # Aggregate affected definitions by owning module.
        modules: Dict[str, Dict[str, int]] = {}
        for r in rows:
            fp = r.get("file_path") or ""
            if not fp:
                continue
            mod = self._module_of(fp)
            agg = modules.setdefault(mod, {"defs": 0, "files": 0})
            agg["defs"] += _to_int(r.get("affected_defs"))
            agg["files"] += 1

        ranked = sorted(modules.items(), key=lambda kv: kv[1]["defs"], reverse=True)
        owners = []
        for i, (mod, agg) in enumerate(ranked):
            owners.append(
                {
                    "user_id": f"area-{i + 1}",
                    "username": mod,
                    "name": "code area (CODEOWNERS pending at deploy)",
                    "affected_definitions": agg["defs"],
                    "services_touched": agg["files"],
                }
            )
        return {"affected_owners": owners}

    def _query_ownership_centrality(self, params: Dict) -> Dict[str, Any]:
        """Query code centrality (high-impact definitions)."""
        sql = """
SELECT
  d.id,
  d.name,
  d.definition_type,
  d.file_path,
  COUNT(DISTINCT e_in.source_id) as inbound_calls,
  COUNT(DISTINCT e_out.target_id) as outbound_calls
FROM gl_definition d
LEFT JOIN gl_edge e_in ON e_in.target_id = d.id AND e_in.relationship_kind = 'CALLS'
LEFT JOIN gl_edge e_out ON e_out.source_id = d.id AND e_out.relationship_kind = 'CALLS'
GROUP BY d.id, d.name, d.definition_type, d.file_path
HAVING (COUNT(DISTINCT e_in.source_id) + COUNT(DISTINCT e_out.target_id)) > 10
ORDER BY (COUNT(DISTINCT e_in.source_id) + COUNT(DISTINCT e_out.target_id)) DESC
LIMIT 30;
"""

        results = self.query_raw(sql)
        return {
            "high_centrality": [
                {
                    "name": r.get("name"),
                    "definition_type": r.get("definition_type"),
                    "inbound": _to_int(r.get("inbound_calls")),
                    "outbound": _to_int(r.get("outbound_calls")),
                }
                for r in results
            ]
        }


if __name__ == "__main__":
    # Quick test
    client = RealOrbitClient()

    if client.health_check():
        print("✓ Orbit connected")

        # Test query
        result = client.query("transitive_dependents", symbols=["allow_all"])
        print(f"\nTransitive dependents of 'allow_all':")
        print(json.dumps(result, indent=2))

        # Test ownership
        result = client.query("ownership_centrality")
        print(f"\nHigh-centrality definitions:")
        print(json.dumps(result, indent=2))
    else:
        print("✗ Orbit not available")
