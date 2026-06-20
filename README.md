# Constellation: Graph-Native DevOps Intelligence

## Overview

Constellation is a multi-agent system that exploits GitLab Orbit's unified SDLC-plus-code property graph to compose DevOps decisions that no single tool can make alone.

**One primitive:** Cross-domain pathfinding and impact traversal
**Four lenses:** Impact, Provenance, Compliance, Ownership
**One verdict:** Composed, evidence-backed recommendation

## Quick Start

### Prerequisites

- GitLab Orbit (Local or Remote)
- Python 3.9+
- git

### Installation

```bash
# Clone the repo
git clone <repo-url> constellation
cd constellation

# (Optional) Create a Python virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies (currently none for MVP)
# pip install -r requirements.txt
```

### Test Locally

```bash
# Test Impact agent
python agents/impact/impact_agent.py

# Test Provenance agent
python agents/provenance/provenance_agent.py

# Test Orchestrator with mock event
cat > /tmp/mr_event.json << 'EOF'
{
  "event_id": "mr-123",
  "event_type": "mr_opened",
  "timestamp": "2026-06-16T12:00:00Z",
  "payload": {
    "mr_id": "mr-123",
    "changed_symbols": ["process_config", "validate_input"]
  }
}
EOF

python orchestrator/orchestrator.py /tmp/mr_event.json
```

### Deploy to GitLab

1. **Create Duo Agent Platform agents**
   - See `agents/impact/agent.yml`, `agents/provenance/agent.yml`
   - Deploy to your GitLab instance via API or UI

2. **Create Duo Agent Platform flow**
   - See `orchestrator/flow.yml`
   - This orchestrates the agents and triggers on MR/finding events

3. **Publish to AI Catalog**
   - Package agents and flow
   - Publish for reuse across projects

## Project Structure

```
constellation/
├── agents/
│   ├── impact/
│   │   ├── impact_agent.py         # Impact agent implementation
│   │   ├── agent.yml               # Agent definition for Duo platform
│   │   └── system-prompt.md        # System instructions
│   ├── provenance/
│   │   ├── provenance_agent.py     # Provenance agent implementation
│   │   ├── agent.yml
│   │   └── system-prompt.md
│   ├── compliance/
│   │   ├── agent.yml
│   │   └── system-prompt.md
│   └── ownership/
│       ├── agent.yml
│       └── system-prompt.md
├── orchestrator/
│   ├── orchestrator.py             # Orchestrator that routes events
│   └── flow.yml                    # Duo Agent Platform flow definition
├── shared/
│   ├── queries.sql                 # Core Orbit queries
│   └── orbit_client.py             # Orbit REST/MCP client (stub)
├── tests/
│   └── fixtures/                   # Sample Orbit outputs for testing
├── AGENTS.md                       # System overview (judges read this)
├── README.md                       # This file
├── LICENSE                         # MIT
└── requirements.txt                # Python dependencies
```

## Architecture

### 5-Layer Stack

```
Layer 1: TRIGGERS
  └─ MR opened, Finding created, Deploy to prod

Layer 2: ORCHESTRATOR (this repo)
  └─ Routes events, composes verdicts

Layer 3: AGENT LENSES
  ├─ Impact: blast radius
  ├─ Provenance: lineage
  ├─ Compliance: control satisfaction
  └─ Ownership: orphan-risk

Layer 4: SHARED QUERY CORE
  └─ Pathfinding, traversal, neighbors, aggregation

Layer 5: GITLAB ORBIT
  └─ Unified SDLC + code property graph
```

## Agents

### Impact Agent

**Problem:** Reviewers approve without seeing transitive dependents.

**Input:** MR with changed symbols
**Output:** Blast radius + affected owners + change-failure prediction

**Status:** ✅ MVP implemented and tested

### Provenance Agent

**Problem:** Vulnerability triage is manual archaeology.

**Input:** Finding with affected symbol
**Output:** Lineage (finding → code → MR → author) + exposure + remediation

**Status:** ✅ MVP implemented and tested

### Compliance Agent

**Problem:** Compliance controls are hand-verified annually.

**Input:** All MRs, pipelines, work items
**Output:** Control satisfaction + violations + evidence

**Status:** 🚧 Registered, queries drafted, not fully implemented

### Ownership Agent

**Problem:** Code ownership decays silently.

**Input:** Code graph + user activity
**Output:** Orphan-risk modules + knowledge-transfer priorities

**Status:** 🚧 Registered, model drafted, not fully implemented

## Composition: The Moat

The key insight: agents compose over **shared context**.

**Flow:**
1. Event triggers → Impact runs first
2. Impact computes blast-radius subgraph, materializes it
3. Subgraph passed to Provenance, Compliance, Ownership
4. Each agent analyzes shared context instead of re-traversing
5. Verdicts composed into one output

**Why this matters:**
- Expensive queries run once, not four times
- Explicit composition: "we all saw the same blast radius"
- System > sum of parts

## Development

### Adding a new agent

1. Create `agents/<agent_name>/` directory
2. Implement `<agent_name>_agent.py`:
   - Subclass or follow the pattern in `impact_agent.py` / `provenance_agent.py`
   - Implement `analyze_*()` method
   - Return a `*Verdict` dataclass
3. Add `agent.yml` with Duo Agent Platform metadata
4. Add `system-prompt.md` with agent instructions
5. Add queries to `shared/queries.sql`
6. Update `orchestrator.py` to route events to the new agent

### Testing

```bash
# Run impact agent tests
python -m pytest tests/test_impact_agent.py -v

# Run provenance agent tests
python -m pytest tests/test_provenance_agent.py -v

# Integration test against real Orbit
python -m pytest tests/test_integration.py -v
```

### Query Development

All Orbit queries are in `shared/queries.sql`. To test:

```bash
# Test against Orbit Local
orbit sql "SELECT COUNT(*) FROM gl_definition"

# Test against Orbit Remote
glab orbit remote query - < shared/queries.sql
```

## Deployment

### Local Development

```bash
python orchestrator/orchestrator.py events/mr_opened.json
```

### GitLab Integration (via Duo Agent Platform)

1. Agents are defined in `agents/*/agent.yml`
2. Flow is defined in `orchestrator/flow.yml`
3. Flow is triggered on events: MR opened, finding created, etc.
4. Output is posted as MR comment or work item

### Cloud Deployment (GitLab AI Catalog)

```bash
# Publish agents to AI Catalog
glab ai catalog publish agents/impact/agent.yml
glab ai catalog publish agents/provenance/agent.yml
glab ai catalog publish orchestrator/flow.yml
```

## Configuration

### Orbit Remote Access (Optional)

If using Orbit Remote, configure:

```bash
export ORBIT_REMOTE_URL="<gitlab-cloud-url>"
export ORBIT_REMOTE_TOKEN="<glab-token>"
export ORBIT_REMOTE_GROUP="<group-path>"
```

### Orbit Local Access (Optional)

If using Orbit Local, configure:

```bash
export ORBIT_LOCAL_DB="~/.orbit/graph.duckdb"
```

## Troubleshooting

### Orbit Local install fails on Windows

Orbit Local installer doesn't support Windows natively. Options:
1. Use WSL (Windows Subsystem for Linux)
2. Use Docker: `docker run -it -v $(pwd):/repo gitlab-org/orbit:latest`
3. Use Orbit Remote (cloud-hosted ClickHouse)

### Agents don't find symbols

Ensure Orbit has indexed the target repo:

```bash
orbit index /path/to/repo
orbit sql "SELECT COUNT(*) FROM gl_definition"
```

### Slow queries

- Check Orbit index freshness (`orbit sql "SELECT MAX(updated_at) FROM gl_definition"`)
- For Orbit Remote, check ClickHouse query performance
- Consider query optimization (limits, filters, recursive depth)

## Contributing

We welcome contributions! Areas for improvement:

1. **Implement Compliance agent** (queries drafted, stub ready)
2. **Implement Ownership agent** (model drafted, stub ready)
3. **Query optimization** (especially Orbit Remote)
4. **Test coverage** (unit + integration tests)
5. **Documentation** (inline code comments, examples)

## License

MIT License. See LICENSE file.

## References

- [GitLab Orbit Documentation](https://docs.gitlab.com/ee/subscriptions/saas/orbit/)
- [GitLab Duo Agent Platform](https://docs.gitlab.com/ee/ai/duo_agent_platform/)
- [Duo Agent Platform MCP](https://docs.gitlab.com/ee/integration/mcp/)
- [DuckDB Documentation](https://duckdb.org/docs/)
- [Constellation Proposal](../proposal.md)

## Questions?

See AGENTS.md for system overview and design decisions.

---

**Constellation:** Graph-Native DevOps Intelligence on GitLab Orbit  
**Team:** AeroFyta  
**Hackathon:** GitLab Transcend (Showcase Track)  
**Deadline:** June 24, 2026
