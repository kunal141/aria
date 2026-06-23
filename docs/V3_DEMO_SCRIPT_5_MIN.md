# ARIA V3 — 5-Minute Demo Script

> **Private internal demo only.** Offline, deterministic, no network, no external
> writes, no deployment. Public release is blocked pending employer/IP approval.

## Setup (before the room)

- One terminal in `apps/backend`.
- The whole story can run from the deterministic proof:
  `uv run python -m aria.demo.v3_proof` (prints each milestone), or step-by-step via the
  local V3 API (`uv run uvicorn ...` then the `/api/v3/...` calls below).
- Everything runs in an isolated, throwaway `ARIA_DATA_DIR`; the repo is left unchanged.

**Pacing:** ~25–30 seconds per step. Total ~5–7 minutes.

---

## The 13-step story

### 1. Business goal intake
- **Show:** give ARIA a vague goal — *"Our notification CTR is dropping. Own this."*
  (`POST /api/v3/goals`).
- **Say:** "I'm not giving it a prompt. I'm giving it a goal — the way you'd brief an
  employee."
- **Proves:** ARIA receives goals, not prompts (V3.1).
- **Boundary:** planning only; no external system touched.

### 2. Problem statement + roadmap
- **Show:** ARIA returns a structured problem statement, success criteria, constraints,
  and a phased roadmap.
- **Say:** "It reframes the ask into a problem it can own, and surfaces what it still
  needs to know."
- **Proves:** goal → governed structure (V3.1).
- **Boundary:** ambiguity becomes clarifying questions, never silent assumptions.

### 3. Task board creation
- **Show:** the roadmap becomes a task board (`GET /goals/{id}/tasks`).
- **Say:** "Now there's a plan of record — tasks, dependencies, evidence needed."
- **Proves:** work decomposition (V3.2).
- **Boundary:** task status is a planning state; moving a task executes nothing.

### 4. Dynamic agent workforce planning
- **Show:** ARIA plans specialist agents (`POST /goals/{id}/agents/plan`) — e.g. data
  freshness, event taxonomy, recommendation impact.
- **Say:** "It assembles the right specialists for this goal — on demand, with bounded
  briefs."
- **Proves:** dynamic workforce (V3.3).
- **Boundary:** dry-run only — a brief is a plan, never a live process; write tools are
  forbidden.

### 5. Agent supervision and governance
- **Show:** the supervised run (`POST /goals/{id}/agents/supervise-run`) — agents are
  governed and **blocked on missing evidence**.
- **Say:** "It doesn't pretend. When evidence is missing, it blocks and says so."
- **Proves:** multi-agent governance (V3.4).
- **Boundary:** dependency / budget / quality / escalation gates; nothing executed.

### 6. Skill gap detection → governed skill proposal
- **Show:** ARIA detects a repeated gap and **proposes a new skill** (`/skills/...`),
  left in `proposed` state.
- **Say:** "It noticed it keeps hitting the same wall — so it proposes a new capability.
  But it can't switch it on itself."
- **Proves:** governed self-improvement (V3.5).
- **Boundary:** proposal-only; activation requires human approval and a safety gate.

### 7. Work Memory Graph lesson
- **Show:** consolidation produces source-linked nodes and a reusable **lesson**
  (`/awareness/work-memory/...`).
- **Say:** "It remembers *how the work went*, not just the data — and every lesson cites
  where it came from."
- **Proves:** institutional memory (V3.6).
- **Boundary:** advisory only; no orphan lessons; can't prove facts without evidence.

### 8. Fixture-only world awareness update
- **Show:** ingest world updates (`/awareness/world/ingest-fixtures`) — cited, relevance-
  scored; a security item escalates.
- **Say:** "It watches approved sources — but from fixtures here, never the live web."
- **Proves:** governed external awareness (V3.6).
- **Boundary:** fixture-only, no live browsing; low-trust can't change the roadmap.

### 9. Draft-only team collaboration update
- **Show:** generate a manager update draft (`/collaboration/drafts`).
- **Say:** "It writes the update a good teammate would send — but it's a draft. It can
  draft, ask, escalate, hand off. It cannot send."
- **Proves:** audience-aware communication (V3.7).
- **Boundary:** draft-only; `is_sendable` is always false; approval ≠ send.

### 10. Scheduled routine summary
- **Show:** create + run a daily review routine (`/routines` + `/routines/{id}/run`).
- **Say:** "It remembers to do recurring work at the right cadence — locally, on demand,
  no hidden scheduler."
- **Proves:** governed recurring work (V3.8).
- **Boundary:** local + deterministic; no cron/daemon/network; outputs are cited.

### 11. Controlled action intent preview / dry-run
- **Show:** create an action intent → **preview** → **dry-run**; then an *external*
  (Teams) target → **blocked** (`/actions/...`).
- **Say:** "Here's the part everyone worries about — taking action. ARIA previews it,
  runs it dry, and the moment it points at a real external system, the gate blocks it."
- **Proves:** controlled live execution (V3.9).
- **Boundary:** deny-by-default; dry-run / internal-mock only; live disabled and store-
  enforced; approval bound to payload + scope.

### 12. Manager dashboard + ROI summary
- **Show:** `POST /dashboard/snapshot` — one read-only view of goals, agents, memory,
  skills, drafts, routines, actions, the approval queue, risks, and **estimated ROI**.
- **Say:** "And here's how you manage it — like an employee. What it worked on, what it
  learned, what it needs, what it risks, and the value it produced."
- **Proves:** manager visibility + ROI (V3.10).
- **Boundary:** read-only; ROI is *estimated*, evidence-backed, no invented cost;
  `live_receipts` is always 0.

### 13. Close on the boundaries
- **Show:** the boundary line in the dashboard / `V3_BOUNDARIES_AND_NON_GOALS.md`.
- **Say:** "Nothing here sent a message, wrote to an external system, browsed the web,
  or deployed. It's governed end to end — and it's private until we choose otherwise."
- **Proves:** governed-by-design.
- **Boundary:** no live writes, no deployment, no public release.

---

## If you only have 90 seconds
Run `uv run python -m aria.demo.v3_proof` and narrate the printed milestone log: goal →
governed agents → skill proposed → lesson learned → draft prepared → routine run →
action dry-run + external blocked → dashboard + ROI. One command, the whole story,
offline.

*Cross-references: [`V3_DEMO_TALK_TRACK.md`](V3_DEMO_TALK_TRACK.md),
[`V3_MANAGER_NARRATIVE.md`](V3_MANAGER_NARRATIVE.md),
[`V3_FINAL_PROOF_DEMO.md`](V3_FINAL_PROOF_DEMO.md).*
