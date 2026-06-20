-- Constellation Real Orbit Queries
-- These queries work against the actual Orbit schema (DuckDB/ClickHouse)
-- Tested against Orbit Local v0.75.1 on knowledge-graph repo

-- Schema reference:
-- gl_definition: id, name, definition_type, file_path, project_id, fqn
-- gl_edge: source_id, target_id, relationship_kind (CALLS, CONTAINS, DEFINES, etc.)
-- gl_file: id, path, language

-- ============================================================================
-- PATTERN 1: IMPACT - Transitive Dependents (Blast Radius)
-- ============================================================================

-- Query 1a: Find functions/classes that directly call a changed symbol
-- INPUT: changed_symbol_names (e.g., 'process_config', 'validate_input')
SELECT
  d_caller.id,
  d_caller.name,
  d_caller.definition_type,
  d_caller.file_path,
  d_target.name AS called_symbol
FROM gl_definition d_target
INNER JOIN gl_edge e ON e.target_id = d_target.id AND e.relationship_kind = 'CALLS'
INNER JOIN gl_definition d_caller ON d_caller.id = e.source_id
WHERE d_target.name IN ('process_config', 'validate_input')
LIMIT 100;

-- Query 1b: Transitive dependents - all code that depends on changed symbols (recursive)
-- This finds the full closure: if A calls B, and C calls A, then both A and C are dependents of B
-- NOTE: `RECURSIVE` must immediately follow `WITH` (not a later CTE name).
-- This mirrors the executed query in shared/orbit_real_client.py.
WITH RECURSIVE changed_symbols AS (
  SELECT id FROM gl_definition
  WHERE name IN ('allow_all', 'compile')
),
transitive_callers AS (
  -- Base case: direct callers of changed symbols
  SELECT
    d.id,
    d.name,
    d.file_path,
    d.definition_type,
    1 as depth
  FROM changed_symbols cs
  INNER JOIN gl_edge e ON e.target_id = cs.id AND e.relationship_kind = 'CALLS'
  INNER JOIN gl_definition d ON d.id = e.source_id

  UNION

  -- Recursive case: callers of the callers
  SELECT
    d.id,
    d.name,
    d.file_path,
    d.definition_type,
    tc.depth + 1
  FROM transitive_callers tc
  INNER JOIN gl_edge e ON e.target_id = tc.id AND e.relationship_kind = 'CALLS'
  INNER JOIN gl_definition d ON d.id = e.source_id
  WHERE tc.depth < 8  -- Bound recursion (graph terminates at depth 3 in practice)
)
SELECT
  COUNT(DISTINCT id) as total_dependents,
  MAX(depth) as max_depth
FROM transitive_callers;

-- Query 1c: Affected services/projects
-- NOTE: single-repo local index => groups by file_path (project_id is constant).
WITH RECURSIVE changed_symbols AS (
  SELECT id FROM gl_definition
  WHERE name IN ('allow_all', 'compile')
),
transitive_callers AS (
  SELECT d.id, d.file_path, 1 as depth
  FROM changed_symbols cs
  INNER JOIN gl_edge e ON e.target_id = cs.id AND e.relationship_kind = 'CALLS'
  INNER JOIN gl_definition d ON d.id = e.source_id

  UNION

  SELECT d.id, d.file_path, tc.depth + 1
  FROM transitive_callers tc
  INNER JOIN gl_edge e ON e.target_id = tc.id AND e.relationship_kind = 'CALLS'
  INNER JOIN gl_definition d ON d.id = e.source_id
  WHERE tc.depth < 8
)
SELECT
  file_path,
  COUNT(DISTINCT id) as affected_definitions
FROM transitive_callers
GROUP BY file_path
ORDER BY affected_definitions DESC;

-- ============================================================================
-- PATTERN 2: PROVENANCE - Lineage Pathfinding
-- ============================================================================

-- Query 2a: For a given symbol, find all symbols that call it
-- This helps understand the blast radius of changing a symbol
SELECT
  source_id,
  target_id,
  d_source.name as caller_name,
  d_target.name as called_name
FROM gl_edge
INNER JOIN gl_definition d_source ON d_source.id = source_id
INNER JOIN gl_definition d_target ON d_target.id = target_id
WHERE d_target.name = 'process_config'
  AND relationship_kind = 'CALLS'
LIMIT 20;

-- Query 2b: Find the definition with most callers (high-impact code)
SELECT
  d.id,
  d.name,
  d.definition_type,
  COUNT(DISTINCT e.source_id) as caller_count
FROM gl_definition d
LEFT JOIN gl_edge e ON e.target_id = d.id AND e.relationship_kind = 'CALLS'
GROUP BY d.id, d.name, d.definition_type
HAVING COUNT(DISTINCT e.source_id) > 0
ORDER BY caller_count DESC
LIMIT 20;

-- ============================================================================
-- PATTERN 3: OWNERSHIP - Code Centrality
-- ============================================================================

-- Query 3a: Code centrality by inbound-call count (caller-count ranking, NOT PageRank)
SELECT
  d.id,
  d.name,
  d.definition_type,
  d.file_path,
  COUNT(DISTINCT e_in.source_id) as inbound_calls,
  COUNT(DISTINCT e_out.target_id) as outbound_calls,
  (COUNT(DISTINCT e_in.source_id) + COUNT(DISTINCT e_out.target_id)) as total_connections
FROM gl_definition d
LEFT JOIN gl_edge e_in ON e_in.target_id = d.id AND e_in.relationship_kind = 'CALLS'
LEFT JOIN gl_edge e_out ON e_out.source_id = d.id AND e_out.relationship_kind = 'CALLS'
GROUP BY d.id, d.name, d.definition_type, d.file_path
HAVING (COUNT(DISTINCT e_in.source_id) + COUNT(DISTINCT e_out.target_id)) > 5
ORDER BY total_connections DESC
LIMIT 30;

-- Query 3b: Find definitions in the same file (potential orphan risk)
SELECT
  f.path,
  f.language,
  COUNT(DISTINCT d.id) as definition_count
FROM gl_file f
LEFT JOIN gl_definition d ON d.file_path = f.path
GROUP BY f.path, f.language
HAVING COUNT(DISTINCT d.id) > 0
ORDER BY definition_count DESC
LIMIT 30;

-- ============================================================================
-- UTILITY QUERIES
-- ============================================================================

-- Schema validation: count entities
SELECT
  'definitions' as entity_type,
  COUNT(*) as count
FROM gl_definition

UNION ALL

SELECT
  'files',
  COUNT(*)
FROM gl_file

UNION ALL

SELECT
  'edges',
  COUNT(*)
FROM gl_edge

UNION ALL

SELECT
  'directories',
  COUNT(*)
FROM gl_directory;

-- List all relationship types and their counts
SELECT
  relationship_kind,
  COUNT(*) as edge_count
FROM gl_edge
GROUP BY relationship_kind
ORDER BY edge_count DESC;

-- Find symbols by name pattern
SELECT
  id,
  name,
  definition_type,
  file_path
FROM gl_definition
WHERE name LIKE '%process%'
LIMIT 10;
