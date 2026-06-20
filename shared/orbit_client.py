#!/usr/bin/env python3
"""
Orbit Client: Unified interface to Orbit Local, Orbit Remote, or glab REST API.

Strategies (in order of preference):
1. Orbit Local (if orbit binary available): fastest, code-only
2. Orbit Remote (via glab orbit remote): full SDLC, requires feature flag
3. glab REST API + hardcoded queries: fallback, no special flag needed
"""

import json
import subprocess
import logging
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrbitBackend(ABC):
    """Abstract base for Orbit access strategies."""

    @abstractmethod
    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """Execute a query and return results."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if this backend is available."""
        pass


class OrbitLocal(OrbitBackend):
    """
    Orbit Local: Single Rust binary, offline, code-only graph.

    Requires: orbit binary installed, target repo indexed.
    Access: orbit sql <sql-query>
    """

    def __init__(self):
        self.available = self._check_orbit_binary()

    def _check_orbit_binary(self) -> bool:
        """Check if orbit binary is in PATH."""
        try:
            result = subprocess.run(
                ["orbit", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info(f"Orbit Local available: {result.stdout.strip()}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        logger.warning("Orbit Local not available (binary not found)")
        return False

    def health_check(self) -> bool:
        return self.available

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """
        Execute Orbit SQL query.

        Args:
            query_type: "transitive_dependents", "lineage", "exposure", etc.
            **kwargs: query-specific parameters

        Returns:
            Query result as dict
        """
        if not self.available:
            raise RuntimeError("Orbit Local not available")

        # Map query_type to SQL
        sql = self._build_query(query_type, kwargs)
        logger.info(f"Orbit Local: executing {query_type}")

        try:
            result = subprocess.run(
                ["orbit", "sql", sql],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"Orbit query failed: {result.stderr}")
                return {}

            # Parse result (assuming JSON output)
            return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.error(f"Orbit query error: {e}")
            return {}

    def _build_query(self, query_type: str, params: Dict) -> str:
        """Build SQL query from template and parameters."""
        templates = {
            "transitive_dependents": """
                WITH RECURSIVE deps AS (
                  SELECT id FROM gl_definition WHERE name IN ({symbols})
                  UNION ALL
                  SELECT caller_id FROM gl_definition_call
                  WHERE callee_id IN (SELECT id FROM deps) AND depth < 5
                )
                SELECT COUNT(*) as count FROM deps;
            """,
            "lineage": """
                SELECT
                  f.id, f.title, d.name, mr.iid, u.username, mr.created_at
                FROM gl_finding f
                JOIN gl_definition d ON d.file_id = f.affected_file_id
                JOIN gl_merge_request mr ON mr.id = (
                  SELECT mr_id FROM gl_definition_history
                  WHERE definition_id = d.id ORDER BY created_at LIMIT 1
                )
                JOIN gl_user u ON mr.author_id = u.id
                WHERE f.id = '{finding_id}';
            """,
        }

        template = templates.get(query_type, "SELECT 1;")

        # Simple parameter substitution (production: use parameterized queries)
        for key, value in params.items():
            template = template.replace(f"{{{key}}}", str(value))

        return template


class OrbitRemote(OrbitBackend):
    """
    Orbit Remote: Cloud-hosted ClickHouse, SDLC-full.

    Requires: glab 1.94+, `knowledge_graph` feature flag, ORBIT_REMOTE_TOKEN
    Access: glab orbit remote query
    """

    def __init__(self, group: Optional[str] = None):
        self.group = group or ""
        self.available = self._check_glab_orbit()

    def _check_glab_orbit(self) -> bool:
        """Check if glab orbit remote is available."""
        try:
            result = subprocess.run(
                ["glab", "orbit", "remote", "schema"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("Orbit Remote available via glab")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        logger.warning("Orbit Remote not available (glab orbit remote schema failed)")
        return False

    def health_check(self) -> bool:
        return self.available

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """
        Execute Orbit Remote query via glab CLI.

        Uses JSON Query DSL (compiled to ClickHouse SQL).
        """
        if not self.available:
            raise RuntimeError("Orbit Remote not available")

        query_dsl = self._build_query_dsl(query_type, kwargs)
        logger.info(f"Orbit Remote: executing {query_type}")

        try:
            result = subprocess.run(
                ["glab", "orbit", "remote", "query", "-"],
                input=json.dumps(query_dsl),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"Orbit Remote query failed: {result.stderr}")
                return {}

            return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.error(f"Orbit Remote query error: {e}")
            return {}

    def _build_query_dsl(self, query_type: str, params: Dict) -> Dict[str, Any]:
        """Build Orbit Query DSL for ClickHouse."""
        templates = {
            "transitive_dependents": {
                "query": {
                    "query_type": "traversal",
                    "node": {
                        "id": "d",
                        "entity": "Definition",
                        "filters": {"name": {"op": "in", "value": params.get("symbols", [])}},
                    },
                    "limit": 1000,
                }
            },
            "lineage": {
                "query": {
                    "query_type": "pathfinding",
                    "start": {"entity": "Finding", "filters": {"id": {"op": "eq", "value": params.get("finding_id")}}},
                    "end": {"entity": "User"},
                    "limit": 1,
                }
            },
        }

        return templates.get(query_type, {"query": {"query_type": "traversal", "node": {}}})


class GlabRESTFallback(OrbitBackend):
    """
    Fallback: Use glab REST API directly.

    Requires: glab authenticated, project accessible
    Access: glab api rest

    Limitations: No graph traversal, only basic SDLC queries
    """

    def __init__(self, group: Optional[str] = None):
        self.group = group or ""
        self.available = self._check_glab_auth()

    def _check_glab_auth(self) -> bool:
        """Check if glab is authenticated."""
        try:
            result = subprocess.run(
                ["glab", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("glab REST API available")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        logger.warning("glab REST API not available (not authenticated)")
        return False

    def health_check(self) -> bool:
        return self.available

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """
        Execute query via glab REST API.

        Limited to SDLC queries (MRs, pipelines, users).
        No code traversal available.
        """
        if not self.available:
            raise RuntimeError("glab REST API not available")

        logger.info(f"glab REST fallback: executing {query_type}")

        # Map query_type to glab API endpoints
        if query_type == "mr_metadata":
            return self._query_mr(kwargs.get("mr_id"))
        elif query_type == "finding_metadata":
            return self._query_finding(kwargs.get("finding_id"))
        else:
            logger.warning(f"Query {query_type} not supported by glab REST fallback")
            return {}

    def _query_mr(self, mr_id: str) -> Dict[str, Any]:
        """Get MR metadata via glab."""
        try:
            result = subprocess.run(
                ["glab", "api", "merge_requests/{mr_id}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return {}

    def _query_finding(self, finding_id: str) -> Dict[str, Any]:
        """Get finding metadata via glab."""
        try:
            result = subprocess.run(
                ["glab", "api", "projects/{project}/vulnerabilities/{finding_id}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return {}


class OrbitClient:
    """
    Unified Orbit client: tries multiple strategies, falls back gracefully.

    Strategies (in order):
    1. Orbit Local (fastest, code-only)
    2. Orbit Remote (full SDLC, requires flag)
    3. glab REST API (fallback, limited)
    """

    def __init__(self):
        self.backends = []
        self._initialize_backends()

    def _initialize_backends(self):
        """Initialize backends in preference order."""
        logger.info("Initializing Orbit client...")

        # Try Orbit Local first
        orbit_local = OrbitLocal()
        if orbit_local.health_check():
            self.backends.append(orbit_local)
            logger.info("✅ Using Orbit Local (code-only, offline)")
        else:
            logger.info("⚠️ Orbit Local unavailable")

        # Try Orbit Remote second
        orbit_remote = OrbitRemote()
        if orbit_remote.health_check():
            self.backends.append(orbit_remote)
            logger.info("✅ Using Orbit Remote (full SDLC)")
        else:
            logger.info("⚠️ Orbit Remote unavailable")

        # Try glab REST as fallback
        glab_rest = GlabRESTFallback()
        if glab_rest.health_check():
            self.backends.append(glab_rest)
            logger.info("✅ Using glab REST API (limited fallback)")
        else:
            logger.info("⚠️ glab REST API unavailable")

        if not self.backends:
            logger.error("❌ No Orbit backends available!")

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a query using the first available backend.

        Tries backends in order until one succeeds.
        """
        if not self.backends:
            logger.error("No Orbit backends initialized")
            return {}

        for backend in self.backends:
            try:
                logger.info(f"Trying {backend.__class__.__name__}...")
                result = backend.query(query_type, **kwargs)
                if result:
                    logger.info(f"✅ {backend.__class__.__name__} succeeded")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ {backend.__class__.__name__} failed: {e}")
                continue

        logger.error(f"All backends failed for {query_type}")
        return {}

    def health_check(self) -> bool:
        """Check if at least one backend is available."""
        return len(self.backends) > 0


if __name__ == "__main__":
    # Test client
    client = OrbitClient()

    if client.health_check():
        print("✅ Orbit client ready")

        # Try a query
        result = client.query("transitive_dependents", symbols=["process_config"])
        print(json.dumps(result, indent=2))
    else:
        print("❌ No Orbit backends available")
        print("\nTo fix:")
        print("1. Install Orbit Local: orbit-cli or Docker")
        print("2. OR request Orbit Remote flag + glab auth")
        print("3. OR ensure glab is authenticated")
