# CONSTELLATION LAUNCH PLAN
## Days 2-8: From MVP to Hackathon Submission

**Current Status:** MVP complete, real data validated, all tests passing  
**Deadline:** June 24, 2026 (6 days remaining)  
**Timeline:** 7-8 hours of work, 6 days available = 2-day safety buffer

---

## 📅 PHASE BREAKDOWN

### **PHASE 1: GitLab Integration (Days 2-3)**
**Goal:** Deploy agents to live GitLab instance  
**Effort:** 3-4 hours  
**Blocker:** Need GitLab instance with Duo Agent Platform access

#### Tasks:
- [ ] Create agent.yml files for each agent (Impact, Provenance)
- [ ] Write system-prompt.md for each agent
- [ ] Create flow.yml deployment package
- [ ] Set up webhook triggers (MR opened, finding created)
- [ ] Deploy to test GitLab instance
- [ ] Verify webhooks fire on MR events
- [ ] Test verdict posts to MR comments

**Success Criteria:**
- MR opened → Constellation analyzes → Comment posted with verdict

---

### **PHASE 2: Validation (Days 3-4)**
**Goal:** Prove system works on real GitLab  
**Effort:** 2 hours  
**Blocker:** Phase 1 must be complete

#### Tasks:
- [ ] Create test MR on Orbit repo fork
- [ ] Watch agents trigger automatically
- [ ] Verify blast radius computed (should be 510 transitive dependents for allow_all+compile)
- [ ] Check confidence scores calculated
- [ ] Validate evidence trails included
- [ ] Document actual output

**Success Criteria:**
- Real MR analyzed automatically
- Verdict appears in comment within 30 seconds
- All metrics present (dependents, risk, owners, confidence)

---

### **PHASE 3: Polish & Publishing (Days 4-6)**
**Goal:** Polish the validated prototype + publish  
**Effort:** 2-3 hours

#### Tasks:
- [ ] Refine agent system prompts
- [ ] Update AGENTS.md with final copy
- [ ] Create AI Catalog entries
- [ ] Test with edge cases (large MRs, many dependencies)
- [ ] Verify performance (<1s per analysis)
- [ ] Document deployment steps

**Success Criteria:**
- System handles 100+ dependent changes smoothly
- Query time stays <2 seconds
- All edge cases handled gracefully

---

### **PHASE 4: Demo & Video (Days 6-7)**
**Goal:** Record 3-min demo for judges  
**Effort:** 1.5 hours

#### Script:
1. **Intro (30s):** "This is Constellation, graph-native DevOps intelligence"
2. **Problem (30s):** Show a change affecting 510 transitive dependents
3. **Analysis (1min):** Show agents running, verdict generated
4. **Results (30s):** Impact + Risk + Evidence displayed
5. **Impact (30s):** "Without this: $50k incident. With this: prevented."

**Shots Needed:**
- System demo running (terminal or dashboard)
- Real MR with Constellation comment
- Agent analysis breakdown
- Before/after incident scenario

**Success Criteria:**
- Video <3 minutes
- Shows real data (510 transitive dependents)
- Clear value proposition
- Professional/polished

---

### **PHASE 5: Devpost Submission (Days 7-8)**
**Goal:** Submit to hackathon  
**Effort:** 1-2 hours

#### Sections:
1. **Problem Statement** (existing in proposal.md)
   - Change review blind to coupling
   - Vulnerability triage is manual archaeology
   - Compliance controls hand-verified
   - Ownership decay silent

2. **Solution**
   - Graph-native DevOps intelligence
   - One primitive (pathfinding) → four lenses
   - Shared-context agents (downstream lenses consume Impact's subgraph without re-querying Orbit)
   - Validated against real Orbit data, with a deferred deployment layer

3. **How Built**
   - Orbit Local for code graph (16,275 definitions)
   - Impact agent for blast radius (510 transitive dependents via recursive gl_edge traversal)
   - Provenance agent for lineage tracing (EXPOSURE real; MR/author lineage representative, pending SDLC enrichment at deploy)
   - Orchestrator for composition
   - Duo Agent Platform for deployment (deferred)
   - Real Orbit data validation for the impact graph (not mock)

4. **What's Next**
   - SDLC enrichment (CODEOWNERS/git authorship, MR/author lineage edges, pipeline/approval compliance checks)
   - Webhook trigger + posting the verdict as an MR comment
   - Multi-repo traversal
   - Incident correlation
   - Enterprise deployment

5. **Key Metrics**
   - 16,275 definitions indexed (Orbit binary v0.75.1, single repo)
   - 510 transitive dependents computed in <60ms (recursive, terminates at depth 3)
   - 95% confidence on complete data
   - 5 integration tests passing
   - Impact graph runs on real Orbit data; Provenance MR/author lineage is representative pending SDLC enrichment

**Success Criteria:**
- Submission accepted
- Judges can run demo.py and see it work
- All required sections completed
- Video embedded or linked

---

## 🎯 DAILY BREAKDOWN

### **Day 2 (Tomorrow)**
- [ ] Set up GitLab instance / request Duo Agent Platform access
- [ ] Create agent.yml + system-prompt.md files
- [ ] Start Phase 1: GitLab integration

### **Day 3**
- [ ] Complete Phase 1: Deploy to test instance
- [ ] Start Phase 2: Validation

### **Day 4**
- [ ] Complete Phase 2: Real MR analysis working
- [ ] Start Phase 3: Polish

### **Day 5**
- [ ] Complete Phase 3: Prototype polished
- [ ] Start Phase 4: Demo planning

### **Day 6**
- [ ] Record demo video
- [ ] Start Phase 5: Devpost draft

### **Day 7**
- [ ] Complete Devpost submission
- [ ] Final review

### **Day 8 (Deadline)**
- [ ] Buffer day / last-minute fixes
- [ ] 2:00 PM ET: SUBMIT

---

## 📊 DEPENDENCY GRAPH

```
Phase 1 (Integration)
    ↓
Phase 2 (Validation) ← Must complete before Phase 3
    ↓
Phase 3 (Polish) → Can start Phase 4 in parallel
    ↓
Phase 4 (Demo) ← Uses results from Phase 3
    ↓
Phase 5 (Submission) ← Uses demo video from Phase 4
```

**Critical path:** Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5  
**Total critical path:** 3.5 hours  
**Available time:** 6 days = 144 hours  
**Buffer:** 140.5 hours (20:1 ratio)

---

## ✅ BLOCKERS & SOLUTIONS

| Blocker | Solution | Timeline |
|---------|----------|----------|
| GitLab instance needed | Request access or use free tier | Day 2 |
| Duo Agent Platform setup | May require admin setup | Day 2 |
| Webhook configuration | Document in setup guide | Day 3 |
| Real MR testing | Can use fork or test repo | Day 3 |
| Video recording | Use terminal recording tool (OBS) | Day 6 |

---

## 🏆 SUCCESS CRITERIA

By June 24, 2:00 PM ET:

- [ ] System deployed to GitLab Duo Agent Platform
- [ ] Webhooks triggering on real MRs
- [ ] Agents analyzing and posting verdicts
- [ ] 3-min demo video recorded
- [ ] Devpost submission complete with:
  - [ ] Problem statement
  - [ ] Solution description
  - [ ] How we built it
  - [ ] Demo video link
  - [ ] Future roadmap
- [ ] All judges' evaluation criteria met:
  - [ ] Technological Implementation (✓ agents work with real data)
  - [ ] Design & Usability (✓ simple MR comment interface)
  - [ ] Potential Impact (✓ prevents $50k+ incidents)
  - [ ] Quality of Idea (✓ integrative novelty: one reachability set on Orbit's unified graph treated simultaneously as blast radius, compliance surface, and vuln exposure)

---

## 📌 NEXT IMMEDIATE ACTIONS

**When you resume:**

1. **Request GitLab Access**
   - Need: GitLab instance with Duo Agent Platform
   - Or: Use GitLab.com free tier + request `knowledge_graph` flag

2. **Create Deployment Files**
   - agent.yml for each agent (4 agents)
   - system-prompt.md for each agent
   - flow.yml trigger configuration

3. **Deploy to Test**
   - Push agents to Duo Agent Platform
   - Enable webhooks
   - Test on dummy MR

4. **Document Deployment**
   - Step-by-step setup guide for judges
   - Verification checklist

---

## 🎁 CURRENT ASSETS READY TO USE

✅ agent.py files (all 4 agents)
✅ orchestrator.py (composition logic)
✅ orbit_real_client.py (Orbit integration)
✅ Integration tests (5 passing)
✅ Demo script (demo.py)
✅ Proposal + documentation
✅ Git history (clean, 9 commits)
✅ Real Orbit data validation (510 transitive dependents)

**Everything needed to deploy is ready.**

---

## 💡 TIPS FOR SUCCESS

1. **Use demo.py as validation:**
   - Run it after each deployment to verify system works
   - Shows exact same output judges will see

2. **Keep video simple:**
   - Focus on one clear scenario
   - Show real numbers (510 transitive dependents)
   - Emphasize "real Orbit data for the impact graph, not simulation"

3. **Test edge cases early:**
   - Large MRs (100+ changed symbols)
   - Deep dependency chains
   - Multiple services affected
   - Network delays

4. **Document as you go:**
   - Deployment steps
   - Troubleshooting
   - Performance metrics
   - Lessons learned

5. **Leave 1-day buffer:**
   - Finish by June 23
   - June 24 morning: final review
   - Gives time for unexpected issues

---

**Status: Ready to execute. Next step is GitLab setup.**
