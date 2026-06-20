# Orbit Setup Guide for Constellation

**Status:** Orbit Local installation requires WSL/Docker + system reboot. Mock backend fully functional for development.

This guide covers setup when you have system access to enable WSL or Docker.

---

## Option A: Orbit Local via WSL (Recommended)

### Prerequisites
- Windows 10/11 with WSL2 support
- Administrator access (for WSL setup)
- ~5 GB disk space

### Steps

#### 1. Enable WSL and Install Ubuntu
```powershell
# Run as Administrator
wsl --install -d Ubuntu
# System will require reboot

# After reboot:
wsl --set-default-version 2
```

#### 2. Initialize Ubuntu (first login)
```bash
# WSL will prompt for username/password on first launch
wsl
# Username: dev
# Password: (create one)
```

#### 3. Install Orbit Local
```bash
wsl bash << 'EOF'
curl -fsSL "https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/raw/main/install.sh" | bash

# Verify installation
orbit --version
EOF
```

#### 4. Clone and Index the Orbit Repo
```bash
wsl bash << 'EOF'
cd /tmp
git clone https://gitlab.com/gitlab-org/orbit/knowledge-graph.git
cd knowledge-graph

# Index the repository (takes 5-10 min)
orbit index .

# Verify indexing
orbit sql "SELECT COUNT(*) FROM gl_definition"
EOF
```

#### 5. Dump Schema (Critical!)
```bash
wsl bash << 'EOF'
orbit sql "SHOW TABLES" > /tmp/orbit_tables.txt
orbit sql "DESCRIBE gl_definition" > /tmp/orbit_gl_definition.txt
orbit sql "DESCRIBE gl_merge_request" > /tmp/orbit_gl_mr.txt
orbit sql "DESCRIBE gl_finding" > /tmp/orbit_finding.txt

# Copy to Windows
cat /tmp/orbit_tables.txt
cat /tmp/orbit_gl_definition.txt
EOF
```

---

## Option B: Orbit Local via Docker

### Prerequisites
- Docker Desktop installed and running
- ~10 GB disk space for image + data

### Steps

#### 1. Pull Orbit Image
```bash
docker pull gitlab-org/orbit:latest
```

#### 2. Run Container
```bash
docker run -it \
  -v /path/to/constellation:/app \
  -v /path/to/orbit/knowledge-graph:/repo \
  gitlab-org/orbit:latest \
  bash
```

#### 3. Inside Container: Index and Dump
```bash
cd /repo
orbit index .
orbit sql "SHOW TABLES"
```

---

## Option C: Orbit Remote (Cloud)

### Prerequisites
- GitLab.com account with API access
- `glab` CLI installed
- `knowledge_graph` feature flag enabled on your group

### Steps

#### 1. Install glab
```bash
# Windows: via Chocolatey or manual
choco install glab

# Or: Download from https://gitlab.com/gitlab-org/cli/-/releases
```

#### 2. Authenticate
```bash
glab auth login
# Follow prompts to create personal access token
```

#### 3. Request Feature Flag
```bash
# Contact GitLab: support@gitlab.com
# Request: `knowledge_graph` feature flag on your group
# Estimated time: 1-2 days
```

#### 4. Test Access
```bash
glab orbit remote schema
glab orbit remote query - < shared/queries.sql
```

---

## Updating Constellation After Setup

Once you have Orbit running, follow these steps:

### 1. Dump the Real Schema
```bash
# From WSL or Docker container:
orbit sql "SHOW TABLES" > /tmp/schema.txt
orbit sql "DESCRIBE gl_definition" > /tmp/gl_def.txt
orbit sql "DESCRIBE gl_merge_request" > /tmp/gl_mr.txt
# ... etc for all entities referenced in shared/queries.sql
```

### 2. Update `shared/queries.sql` with Real Column Names
Compare the mock column names against actual schema and update:
```sql
-- Example: if real schema uses "file_path" instead of "name"
SELECT file_path FROM gl_definition WHERE ...
```

### 3. Test Queries Against Real Orbit
```bash
# From WSL:
orbit sql "SELECT COUNT(*) FROM gl_definition LIMIT 10"

# Should return real data from Orbit repo
```

### 4. Swap Mock for Real Client
**Single change in the agents:**

**Before (mock):**
```python
from shared.orbit_mock import MockOrbitClient
orbit_client = MockOrbitClient()
```

**After (real Orbit):**
```python
from shared.orbit_client import OrbitClient
orbit_client = OrbitClient()
```

### 5. Run Integration Tests Again
```bash
cd constellation
python tests/integration_test.py
# Should pass with real Orbit data instead of mock
```

---

## Troubleshooting

### WSL Installation Fails
- **Error:** "Operation requires elevation"
  - Run PowerShell as Administrator
  - May require system reboot after WSL install

- **Error:** "WSL 2 requires update"
  - Download: https://aka.ms/wsl2kernel
  - Install and reboot

### Docker Container Won't Start
- **Error:** "Docker daemon not running"
  - Open Docker Desktop from Start menu
  - Wait 30 seconds for initialization
  - Try again

- **Error:** "Image not found"
  - Run: `docker pull gitlab-org/orbit:latest`

### Orbit Index Takes Too Long
- Indexing 11k+ file repo with 100k+ definitions: 5-10 minutes normal
- Monitor: `orbit sql "SELECT COUNT(*) FROM gl_file"` (should increase over time)

### Query Returns Empty Results
- **Check:** `orbit sql "SELECT COUNT(*) FROM gl_definition"` 
  - If 0: indexing not complete, wait longer
  - If >0: query syntax error, check column names

---

## Current Status: Mock vs Real

| Feature | Mock | Real Orbit |
|---------|------|-----------|
| **Blast Radius** | ✅ Working (14 dependents) | ✅ Ready (swap client) |
| **Vulnerability Lineage** | ✅ Working (5-step chain) | ✅ Ready (swap client) |
| **Compliance** | ✅ Queries drafted | ⏳ Needs real data |
| **Ownership** | ✅ Model drafted | ⏳ Needs real data |
| **Integration Tests** | ✅ All passing | ⏳ Swap & retest |
| **Confidence Scoring** | ✅ Logic complete | ✅ Ready to tune |

**To go live:** WSL/Docker setup (1-2 hours) + schema dump (15 min) + client swap (5 min) = ~2 hours to real data.

---

## Integration Points

Once Orbit is available, these integration points will activate:

1. **orbit_client.py** — switches from mock to real queries
2. **Impact agent** — computes real blast radius from real code graph
3. **Provenance agent** — traces real vulnerability lineage
4. **Tests** — rerun with real data to validate accuracy

All backend logic is ready. Just waiting for the graph.

---

## Next Steps

**Immediate (now):**
- Keep mock backend for rapid iteration
- Continue with flow.yml design (Day 4 work)
- Have everything ready to integrate Orbit

**When Orbit is available:**
1. Run WSL/Docker setup (~2 hours)
2. Dump schema and update queries
3. Swap client import
4. Rerun tests with real data
5. Verify accuracy on real repositories

**Timeline:** Orbit setup should take ~2 hours total. Can happen in parallel with flow integration.

---

## References

- Orbit Documentation: https://docs.gitlab.com/ee/subscriptions/saas/orbit/
- Orbit GitHub: https://gitlab.com/gitlab-org/orbit/knowledge-graph
- WSL Installation: https://learn.microsoft.com/en-us/windows/wsl/install
- Docker Installation: https://docs.docker.com/desktop/install/windows-install/

