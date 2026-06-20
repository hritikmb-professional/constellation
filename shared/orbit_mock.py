#!/usr/bin/env python3
"""
Mock Orbit Backend: Simulates realistic Orbit responses for testing.

This allows us to:
1. Test the full agent composition pipeline
2. Demonstrate the system to judges
3. Iterate quickly without waiting for Orbit infrastructure

When real Orbit is available, swap this out for the real orbit_client.py
"""

import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockOrbitBackend:
    """Mock Orbit that returns realistic data."""

    def __init__(self):
        self.available = True
        logger.info("Using Mock Orbit Backend (for testing)")

    def health_check(self) -> bool:
        return True

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """Return realistic mock data based on query type."""
        logger.info(f"Mock Orbit: executing {query_type}")

        if query_type == "transitive_dependents":
            return self._mock_transitive_dependents(kwargs)
        elif query_type == "affected_services":
            return self._mock_affected_services(kwargs)
        elif query_type == "affected_owners":
            return self._mock_affected_owners(kwargs)
        elif query_type == "lineage":
            return self._mock_lineage(kwargs)
        elif query_type == "exposure_scope":
            return self._mock_exposure_scope(kwargs)
        else:
            logger.warning(f"Unknown query type: {query_type}")
            return {}

    def _mock_transitive_dependents(self, params: Dict) -> Dict[str, Any]:
        """Mock: transitive dependents of changed symbols."""
        symbols = params.get("symbols", ["process_config"])

        return {
            "total_dependents": 14,
            "affected_services": 3,
            "service_ids": ["api-svc", "data-svc", "worker-svc"],
            "max_depth": 4,
            "median_depth": 2.5,
            "affected_definitions": [
                {"id": "def-1", "name": "validate_request", "service": "api-svc", "depth": 1},
                {"id": "def-2", "name": "handle_config", "service": "api-svc", "depth": 2},
                {"id": "def-3", "name": "load_config", "service": "data-svc", "depth": 1},
                {"id": "def-4", "name": "sync_worker", "service": "worker-svc", "depth": 3},
            ],
        }

    def _mock_affected_services(self, params: Dict) -> Dict[str, Any]:
        """Mock: affected services/projects."""
        return {
            "affected_services": [
                {
                    "project_id": "p1",
                    "project_name": "api-service",
                    "full_path": "microservices/api-service",
                    "affected_definitions": 6,
                    "is_critical_path": True,
                    "last_deploy": "2026-06-15T10:30:00Z",
                },
                {
                    "project_id": "p2",
                    "project_name": "data-service",
                    "full_path": "microservices/data-service",
                    "affected_definitions": 5,
                    "is_critical_path": False,
                    "last_deploy": "2026-06-14T15:45:00Z",
                },
                {
                    "project_id": "p3",
                    "project_name": "worker-service",
                    "full_path": "microservices/worker-service",
                    "affected_definitions": 3,
                    "is_critical_path": False,
                    "last_deploy": "2026-06-13T08:00:00Z",
                },
            ]
        }

    def _mock_affected_owners(self, params: Dict) -> Dict[str, Any]:
        """Mock: owners of affected code."""
        return {
            "affected_owners": [
                {
                    "user_id": "u1",
                    "username": "alice",
                    "name": "Alice Chen",
                    "email": "alice@example.com",
                    "affected_definitions": 8,
                    "services_touched": 2,
                    "last_commit": "2026-06-15",
                },
                {
                    "user_id": "u2",
                    "username": "bob",
                    "name": "Bob Smith",
                    "email": "bob@example.com",
                    "affected_definitions": 6,
                    "services_touched": 2,
                    "last_commit": "2026-06-12",
                },
            ]
        }

    def _mock_lineage(self, params: Dict) -> Dict[str, Any]:
        """Mock: vulnerability lineage (finding -> symbol -> MR -> author)."""
        finding_id = params.get("finding_id", "cve-2026-1234")

        return {
            "lineage": [
                {
                    "step": 1,
                    "entity_type": "finding",
                    "entity_id": finding_id,
                    "entity_name": "CVE-2026-1234: RCE in yaml.load()",
                    "metadata": {
                        "severity": "CRITICAL",
                        "cvss_score": 9.1,
                        "description": "Unsafe deserialization in YAML parser",
                    },
                },
                {
                    "step": 2,
                    "entity_type": "symbol",
                    "entity_id": "process_config",
                    "entity_name": "process_config()",
                    "metadata": {
                        "file": "src/config/parser.rs",
                        "line": 234,
                        "language": "rust",
                    },
                },
                {
                    "step": 3,
                    "entity_type": "definition",
                    "entity_id": "def-456",
                    "entity_name": "process_config() -> Config",
                    "metadata": {
                        "project": "knowledge-graph",
                        "file": "src/config/parser.rs",
                        "lines": "230-250",
                    },
                },
                {
                    "step": 4,
                    "entity_type": "merge_request",
                    "entity_id": "mr-2456",
                    "entity_name": "!2456",
                    "metadata": {
                        "title": "Add YAML config parser",
                        "date": "2026-03-15T14:30:00Z",
                        "author_id": "u1",
                        "author_username": "alice",
                        "url": "https://gitlab.com/orbit/knowledge-graph/-/merge_requests/2456",
                    },
                },
                {
                    "step": 5,
                    "entity_type": "author",
                    "entity_id": "u1",
                    "entity_name": "alice@example.com",
                    "metadata": {
                        "name": "Alice Chen",
                        "username": "alice",
                        "team": "platform",
                    },
                },
            ]
        }

    def _mock_exposure_scope(self, params: Dict) -> Dict[str, Any]:
        """Mock: which services are exposed to a vulnerability."""
        finding_id = params.get("finding_id", "cve-2026-1234")

        return {
            "exposure": [
                {
                    "project_id": "p1",
                    "project_name": "api-service",
                    "full_path": "microservices/api-service",
                    "is_reachable": True,
                    "is_deployed": True,
                    "last_deployment": "2026-06-15T10:30:00Z",
                    "deploy_env": "prod",
                },
                {
                    "project_id": "p2",
                    "project_name": "config-service",
                    "full_path": "microservices/config-service",
                    "is_reachable": True,
                    "is_deployed": True,
                    "last_deployment": "2026-06-14T15:45:00Z",
                    "deploy_env": "prod",
                },
            ],
            "is_critical_path": True,
            "critical_services": ["config-service"],
        }


class MockOrbitClient:
    """Unified mock client matching the real OrbitClient interface."""

    def __init__(self):
        self.backend = MockOrbitBackend()
        logger.info("Initialized Mock Orbit Client (for testing/demo)")

    def query(self, query_type: str, **kwargs) -> Dict[str, Any]:
        """Execute query using mock backend."""
        return self.backend.query(query_type, **kwargs)

    def health_check(self) -> bool:
        """Check if client is ready."""
        return self.backend.health_check()


if __name__ == "__main__":
    # Test mock client
    client = MockOrbitClient()

    print("Testing Mock Orbit Client\n")

    # Test transitive dependents
    result = client.query("transitive_dependents", symbols=["process_config"])
    print("transitive_dependents:")
    print(json.dumps(result, indent=2))
    print()

    # Test affected services
    result = client.query("affected_services")
    print("affected_services:")
    print(json.dumps(result, indent=2))
    print()

    # Test lineage
    result = client.query("lineage", finding_id="cve-2026-1234")
    print("lineage:")
    print(json.dumps(result, indent=2))
    print()

    # Test exposure
    result = client.query("exposure_scope")
    print("exposure_scope:")
    print(json.dumps(result, indent=2))
