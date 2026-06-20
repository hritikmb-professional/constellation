-- Constellation: Shared Query Core for Orbit
-- These queries are instantiated per agent

-- ============================================================================
-- PATTERN 1: IMPACT - Transitive Dependents (Blast Radius)
-- ============================================================================
-- Input: changed_symbol_names (array of function/class names that changed)
-- Output: all symbols that transitively depend on changed_symbol_names
--
-- Use Case: When a developer changes a symbol, which other code breaks?

-- Query 1a: Direct dependents (one level)
SELECT DISTINCT
  callee.id as changed_symbol_id,
  callee.name as changed_symbol_name,
  caller.id as dependent_id,
  caller.name as dependent_name,
  caller.file_id,
  caller.project_id,
  'direct' as dependency_type
FROM gl_definition caller
INNER JOIN gl_definition_call USING (caller_id)
INNER JOIN gl_definition callee ON callee.id = gl_definition_call.callee_id
WHERE callee.name IN ('process_config', 'validate_input');  -- PARAMETERIZE

-- Query 1b: Transitive dependents (recursive)
-- This finds the full closure of all code that depends on changed symbols
WITH RECURSIVE transitive_deps AS (
  -- Base case: changed symbols
  SELECT
    id,
    name,
    file_id,
    project_id,
    0 as depth
  FROM gl_definition
  WHERE name IN ('process_config', 'validate_input')  -- PARAMETERIZE

  UNION ALL

  -- Recursive case: callers of those symbols
  SELECT
    caller.id,
    caller.name,
    caller.file_id,
    caller.project_id,
    depth + 1
  FROM gl_definition caller
  INNER JOIN gl_definition_call ON caller.id = gl_definition_call.caller_id
  INNER JOIN transitive_deps ON transitive_deps.id = gl_definition_call.callee_id
  WHERE depth < 5  -- Limit recursion depth to avoid explosion
)
SELECT
  COUNT(DISTINCT id) as total_dependents,
  COUNT(DISTINCT project_id) as affected_services,
  ARRAY_AGG(DISTINCT project_id) as service_ids,
  MAX(depth) as max_call_depth,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY depth) as median_depth
FROM transitive_deps
WHERE depth > 0;  -- Exclude the changed symbol itself

-- Query 1c: Service mapping (which repos are affected?)
WITH transitive_deps AS (
  -- (same recursive CTE as above)
)
SELECT
  p.id as project_id,
  p.name as project_name,
  p.full_path,
  COUNT(DISTINCT td.id) as affected_definitions,
  ARRAY_AGG(DISTINCT td.name) as affected_symbols
FROM transitive_deps td
INNER JOIN gl_project p ON p.id = td.project_id
WHERE td.depth > 0
GROUP BY p.id, p.name, p.full_path
ORDER BY affected_definitions DESC;

-- Query 1d: Authors of affected code (ownership)
WITH transitive_deps AS (
  -- (same recursive CTE)
)
SELECT
  u.id,
  u.username,
  u.name,
  COUNT(DISTINCT td.id) as affected_definitions,
  COUNT(DISTINCT td.project_id) as services_touched
FROM transitive_deps td
INNER JOIN gl_file f ON f.id = td.file_id
INNER JOIN gl_file_authorship fa ON fa.file_id = f.id
INNER JOIN gl_user u ON u.id = fa.user_id
WHERE td.depth > 0
GROUP BY u.id, u.username, u.name
ORDER BY affected_definitions DESC;

-- ============================================================================
-- PATTERN 2: PROVENANCE - Lineage Pathfinding
-- ============================================================================
-- Input: finding_id (vulnerability finding)
-- Output: finding → symbol → definition → introducing MR → author → deployment status
--
-- Use Case: How was this vulnerability introduced? Who can fix it? Where is it deployed?

-- Query 2a: Finding to symbol to definition
SELECT
  f.id as finding_id,
  f.title as finding_title,
  f.severity,
  f.cvss_score,
  d.id as definition_id,
  d.name as definition_name,
  d.file_id,
  d.project_id,
  f.created_at
FROM gl_finding f
INNER JOIN gl_definition d ON d.file_id = f.affected_file_id
WHERE f.id = 'cve-2026-1234';  -- PARAMETERIZE

-- Query 2b: Definition to introducing merge request (via blame)
-- Find which MR first introduced this definition
WITH definition_intro AS (
  SELECT
    d.id as definition_id,
    d.name,
    MIN(dh.created_at) as first_seen_at,
    dh.merge_request_id  -- This assumes Orbit tracks MR origin
  FROM gl_definition d
  INNER JOIN gl_definition_history dh ON dh.definition_id = d.id
  WHERE d.id = 'process_config'  -- PARAMETERIZE (from finding)
  GROUP BY d.id, d.name, dh.merge_request_id
)
SELECT
  di.definition_id,
  di.name,
  mr.id as mr_id,
  mr.iid,
  mr.title,
  mr.created_at as mr_date,
  mr.author_id,
  u.username as author_username,
  u.name as author_name,
  u.email as author_email
FROM definition_intro di
INNER JOIN gl_merge_request mr ON mr.id = di.merge_request_id
INNER JOIN gl_user u ON u.id = mr.author_id;

-- Query 2c: Exposure scope (which deployed services reach this symbol?)
WITH reachable AS (
  -- Find all services that can reach the vulnerable symbol
  WITH RECURSIVE call_chain AS (
    SELECT
      id, name, project_id, 0 as depth
    FROM gl_definition
    WHERE name = 'process_config'  -- PARAMETERIZE

    UNION ALL

    SELECT
      caller.id, caller.name, caller.project_id, depth + 1
    FROM gl_definition caller
    INNER JOIN gl_definition_call ON caller.id = gl_definition_call.caller_id
    INNER JOIN call_chain ON call_chain.id = gl_definition_call.callee_id
    WHERE depth < 10
  )
  SELECT DISTINCT project_id FROM call_chain
)
SELECT
  p.id as project_id,
  p.name as project_name,
  p.full_path,
  (CASE WHEN j.status = 'success' AND j.job_type = 'deploy' THEN TRUE ELSE FALSE END) as is_deployed,
  MAX(j.created_at) as last_deployment
FROM reachable r
INNER JOIN gl_project p ON p.id = r.project_id
LEFT JOIN gl_job j ON j.project_id = p.id AND j.job_type = 'deploy'
GROUP BY p.id, p.name, p.full_path;

-- ============================================================================
-- PATTERN 3: COMPLIANCE - Standing Queries
-- ============================================================================
-- Input: control definition (e.g., "MRs to default deploying to prod")
-- Output: which MRs violate the control and why

-- Query 3a: Control 1 - Non-author approval on prod-deploy MRs
-- "All MRs merged to default branch deploying to prod must have non-author approval"
SELECT
  mr.id,
  mr.iid,
  mr.title,
  mr.state,
  mr.merged_at,
  mr.author_id,
  author.username as author_username,
  COALESCE(approvals.non_author_count, 0) as non_author_approvals,
  (CASE
    WHEN approvals.non_author_count > 0 THEN 'PASS'
    ELSE 'FAIL'
  END) as control_status,
  (CASE
    WHEN approvals.non_author_count > 0 THEN NULL
    ELSE 'Missing non-author approval'
  END) as violation_reason
FROM gl_merge_request mr
INNER JOIN gl_user author ON author.id = mr.author_id
LEFT JOIN (
  SELECT
    mr_id,
    COUNT(*) as non_author_count
  FROM gl_merge_request_approval
  WHERE user_id != mr.author_id
  GROUP BY mr_id
) approvals ON approvals.mr_id = mr.id
WHERE
  mr.target_branch = 'main'
  AND mr.state = 'merged'
  AND mr.created_at > NOW() - INTERVAL 90 DAY
ORDER BY mr.merged_at DESC;

-- Query 3b: Control 2 - Passing pipeline on prod-deploy MRs
SELECT
  mr.id,
  mr.iid,
  mr.title,
  pipeline.status as pipeline_status,
  (CASE
    WHEN pipeline.status = 'success' THEN 'PASS'
    ELSE 'FAIL'
  END) as control_status,
  (CASE
    WHEN pipeline.status != 'success' THEN CONCAT('Pipeline failed: ', pipeline.status)
    ELSE NULL
  END) as violation_reason
FROM gl_merge_request mr
LEFT JOIN gl_pipeline pipeline ON pipeline.mr_id = mr.id
WHERE
  mr.target_branch = 'main'
  AND mr.state = 'merged'
  AND mr.created_at > NOW() - INTERVAL 90 DAY;

-- ============================================================================
-- PATTERN 4: OWNERSHIP - Orphan-Risk Detection
-- ============================================================================
-- Input: none (runs on full graph)
-- Output: high-centrality symbols with low author redundancy and stale commits

-- Query 4a: Code centrality by inbound-call count (caller-count ranking)
-- NOTE: this is a simple inbound-call-count ranking, NOT PageRank/betweenness.
WITH centrality AS (
  SELECT
    d.id,
    d.name,
    d.project_id,
    COUNT(DISTINCT dca.caller_id) as inbound_call_count,
    COUNT(DISTINCT dcb.callee_id) as outbound_call_count,
    (COUNT(DISTINCT dca.caller_id) + COUNT(DISTINCT dcb.callee_id)) as total_connections
  FROM gl_definition d
  LEFT JOIN gl_definition_call dca ON dca.callee_id = d.id
  LEFT JOIN gl_definition_call dcb ON dcb.caller_id = d.id
  GROUP BY d.id, d.name, d.project_id
)
SELECT
  id,
  name,
  project_id,
  total_connections,
  PERCENT_RANK() OVER (ORDER BY total_connections) as centrality_percentile
FROM centrality
WHERE total_connections > 5
ORDER BY centrality_percentile DESC
LIMIT 20;

-- Query 4b: Authorship decay (stale definitions with few recent authors)
SELECT
  d.id,
  d.name,
  d.project_id,
  COUNT(DISTINCT fa.user_id) as author_count,
  MAX(EXTRACT(DAY FROM (NOW() - fa.updated_at))) as days_since_last_update,
  (CASE
    WHEN author_count <= 2 AND days_since_last_update > 180 THEN 'HIGH'
    WHEN author_count <= 2 AND days_since_last_update > 90 THEN 'MEDIUM'
    ELSE 'LOW'
  END) as orphan_risk
FROM gl_definition d
INNER JOIN gl_file f ON f.id = d.file_id
INNER JOIN gl_file_authorship fa ON fa.file_id = f.id
GROUP BY d.id, d.name, d.project_id
HAVING author_count <= 2
ORDER BY days_since_last_update DESC;

-- ============================================================================
-- HELPER: Confidence Scoring Logic
-- ============================================================================
-- These metrics inform confidence scores (0.0-1.0)

-- Metric 1: Code graph completeness
-- What % of the codebase is indexed?
SELECT
  COUNT(*) as total_definitions,
  COUNT(CASE WHEN project_id IS NOT NULL THEN 1 END) as mapped_definitions,
  ROUND(100.0 * COUNT(CASE WHEN project_id IS NOT NULL THEN 1 END) / COUNT(*), 2) as coverage_percent,
  (CASE
    WHEN ROUND(100.0 * COUNT(CASE WHEN project_id IS NOT NULL THEN 1 END) / COUNT(*), 2) >= 95 THEN 0.99
    WHEN ROUND(100.0 * COUNT(CASE WHEN project_id IS NOT NULL THEN 1 END) / COUNT(*), 2) >= 90 THEN 0.95
    WHEN ROUND(100.0 * COUNT(CASE WHEN project_id IS NOT NULL THEN 1 END) / COUNT(*), 2) >= 80 THEN 0.85
    ELSE 0.70
  END) as confidence_multiplier
FROM gl_definition;

-- Metric 2: MR lineage completeness
-- Can we trace introduced-by relationships?
SELECT
  COUNT(*) as total_definitions,
  COUNT(dh.merge_request_id) as with_lineage,
  ROUND(100.0 * COUNT(dh.merge_request_id) / COUNT(*), 2) as lineage_coverage_percent
FROM gl_definition d
LEFT JOIN gl_definition_history dh ON dh.definition_id = d.id AND dh.is_intro = TRUE;
