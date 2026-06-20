# Constellation GitLab Deployment Guide

**Status:** Validated prototype for Duo Agent Platform (validated against real Orbit data, with a deferred deployment layer)  
**Last Updated:** June 18, 2026  
**Deadline:** June 24, 2026

---

## 📋 Pre-Deployment Checklist

- [ ] GitLab account created (https://gitlab.com/sign_up)
- [ ] Test repository created (constellation-test or similar)
- [ ] Duo Agent Platform access requested
- [ ] Webhook permissions enabled on repository
- [ ] Python 3.8+ and git installed locally

---

## 🚀 Deployment Steps

### **Step 1: Clone Test Repository**

```bash
git clone https://gitlab.com/hritikmb-professional/constellation-test.git
cd constellation-test
```

### **Step 2: Copy Constellation Files**

From your local Constellation project, copy these directories:

```bash
# Copy agent definitions
cp -r .gitlab/ constellation-test/.gitlab/

# Copy agents code
cp -r agents/ constellation-test/agents/
cp -r shared/ constellation-test/shared/
cp -r orchestrator/ constellation-test/orchestrator/

# Copy supporting files
cp demo.py constellation-test/
cp tests/integration_test.py constellation-test/tests/
cp bin/orbit.exe constellation-test/bin/
```

### **Step 3: Create GitLab CI Configuration**

Create `.gitlab-ci.yml` for testing (optional, enables CI validation):

```yaml
stages:
  - test
  - deploy

test:agents:
  stage: test
  script:
    - python -m pytest tests/integration_test.py -v
  only:
    - main
    - develop

validate:flow:
  stage: test
  script:
    - python -c "import yaml; yaml.safe_load(open('.gitlab/flow.yml'))"
  only:
    - main
```

### **Step 4: Enable Duo Agent Platform**

**Option A: Request Access (Recommended)**

1. Go to **https://gitlab.com/groups/hritikmb-professional/-/settings/integrations**
2. Look for **Duo Agent Platform** section
3. Click **Request Access** or **Enable**
4. Wait for GitLab admin approval (may take 1-2 days)

**Option B: Use GitLab.com (Instant)**

1. Some features available on gitlab.com free tier
2. Check **Settings** → **Integrations** → **Agents**
3. Enable if available

### **Step 5: Register Agents**

Once Duo Agent Platform is enabled:

1. Go to **Repository Settings** → **Integrations** → **Agents**
2. Click **New Agent**
3. Enter agent name: `impact`
4. Click **Create**
5. Repeat for: `provenance`, `compliance`, `ownership`

Alternative (CLI):

```bash
# If GitLab CLI is installed
glab agent create impact .gitlab/agents/impact/agent.yml
glab agent create provenance .gitlab/agents/provenance/agent.yml
glab agent create compliance .gitlab/agents/compliance/agent.yml
glab agent create ownership .gitlab/agents/ownership/agent.yml
```

### **Step 6: Enable Webhooks**

> **Note:** The webhook trigger and posting the verdict back as an MR comment are deferred (not yet wired up). The orchestrator currently runs the full four-lens composition over real Orbit data; the steps below describe the deploy-time wiring that remains to be completed.

For Constellation to trigger on MR/finding events:

1. Go to **Settings** → **Webhooks**
2. Add webhook:
   - **URL:** `https://your-constellation-webhook.example.com/webhook`
     (Or use GitLab's built-in webhook handlers)
   - **Trigger:** Merge requests opened/updated
   - **SSL verification:** Enabled

3. Add second webhook:
   - **URL:** Same as above
   - **Trigger:** Security findings created
   - **SSL verification:** Enabled

### **Step 7: Push to Repository**

```bash
cd constellation-test
git add .
git commit -m "Add Constellation agents and flow configuration"
git push origin main
```

### **Step 8: Test Locally First**

Before deploying to GitLab, verify everything works locally:

```bash
# Run integration tests
python tests/integration_test.py

# Run demo
python demo.py

# Expected output: All tests pass, demo shows 510 transitive dependents
```

---

## ✅ Verification Checklist

After deployment:

- [ ] All 4 agents registered in GitLab
- [ ] `.gitlab/flow.yml` present and valid
- [ ] Webhooks configured and active
- [ ] Test MR can be created without errors
- [ ] Agent responds within 30 seconds
- [ ] Comment posted to MR with analysis
- [ ] All metrics present (dependents, risk, owners)

---

## 🔧 Troubleshooting

### **Agents Not Triggering**

**Problem:** MR opened but no agent runs  
**Solutions:**
1. Check webhooks are enabled (Settings → Webhooks)
2. Verify Duo Agent Platform access is enabled
3. Check agent registration (Settings → Integrations → Agents)
4. Review agent logs (Settings → Integrations → Agent Details)

### **Agent Times Out**

**Problem:** Analysis takes >60 seconds  
**Solutions:**
1. Optimize Orbit queries (reduce symbols analyzed per call)
2. Increase timeout in `.gitlab/flow.yml` (max 300s)
3. Check Orbit database is accessible
4. Verify network connectivity to Orbit Local

### **Comment Not Posted to MR**

**Problem:** Analysis completes but no MR comment  
**Solutions:**
1. Check MR comment permissions (Settings → Members)
2. Verify orchestrator.py is posting correctly
3. Check GitLab API token has `api` + `write_repository` scopes
4. Review agent logs for errors

### **Permission Denied**

**Problem:** "403 Forbidden" errors  
**Solutions:**
1. Ensure GitLab user has Maintainer+ role in repo
2. Verify personal access token has `api` scope
3. Check webhook secret is configured
4. Ensure CI/CD pipeline permissions are enabled

---

## 📊 Monitoring & Maintenance

### **Check Agent Health**

```bash
# List all agents
glab agent list

# Get agent details
glab agent get impact

# View agent logs (if available)
glab agent logs impact --tail 50
```

### **Performance Metrics**

Expected performance:
- **Analysis time:** <1 second (recursive Orbit blast-radius query is <60ms)
- **Comment posting:** <5 seconds (GitLab API) — posting the verdict as an MR comment is deferred
- **Total MR feedback:** <10 seconds

### **Update Agents**

When system-prompts change:

```bash
# Edit system-prompt.md
nano .gitlab/agents/impact/system-prompt.md

# Commit and push
git add .gitlab/
git commit -m "Update Impact agent prompt"
git push origin main

# GitLab automatically redeploys agents
```

---

## 🎯 Next Steps

1. **Deploy to test repo** (today)
2. **Request Duo Agent Platform access** (if needed)
3. **Create test MR** (tomorrow)
4. **Validate end-to-end** (confirm comment posts)
5. **Record demo video** (days 6-7)
6. **Submit to hackathon** (June 24)

---

## 📞 Support

If you encounter issues:

1. **Check logs**: Settings → Integrations → Agents → [agent name] → Logs
2. **Run local demo**: `python demo.py`
3. **Review code**: agents/*.py
4. **Test queries**: Run integration tests

---

## 🏆 Success Criteria

Deployment is successful when:

✅ MR opened → agents trigger automatically  
✅ Analysis completes in <10 seconds  
✅ Comment posted to MR with verdict  
✅ All metrics displayed (dependents, risk, owners, compliance)  
✅ Judges can see it working

---

**Validated prototype — the four-lens orchestrator runs against real Orbit data today. To deploy, complete the deferred layer (webhook trigger, MR-comment posting, and SDLC enrichment), then push to your repo and request Duo Agent Platform access.**
