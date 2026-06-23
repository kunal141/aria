# ARIA V3 — Business Presentation (Slide Deck)

> **Executive deck — private internal pilot.** Documentation/packaging only. Public
> release is blocked pending employer/IP approval; V4 has not started. This markdown is
> the source of truth; the generated PPTX
> (`docs/presentations/ARIA_V3_Governed_AI_Employee_Workforce.pptx`) mirrors it.
>
> **Proof points (real):** V3 focused tests **371 passed**; full backend **1577 passed,
> 1 skipped**; tag `aria-v3-goal-driven-workforce` → endpoint `17021ef`; V3 merged
> locally into `master` (`13a33ad`); public release blocked pending employer/IP approval.

---

## Slide 1 — Title

**Title:** ARIA V3 — Governed AI Employee Workforce
**Subtitle:** From an AI that answers to an AI that owns work — under governance.

- **Objective:** Set the frame: this is an AI *employee system*, not an assistant.
- **Bullets:**
  - ARIA = Autonomous Role-based Intelligence Agent
  - V3: Goal-Driven AI Employee Workforce — COMPLETE
  - Private internal pilot · public release pending approval
- **Suggested visual:** Clean title slide; ARIA wordmark; a faint "goal → plan → act →
  learn → report" arc across the bottom.
- **Speaker notes:** "ARIA isn't another chatbot. It's a governed AI employee system —
  it owns a goal end to end, under control. I'll show you what that means and why it
  matters for us."

---

## Slide 2 — The Problem

**Title:** AI Tools Answer. Businesses Need Work Ownership.

- **Objective:** Name the gap between "AI that answers" and "AI you can trust with work."
- **Bullets:**
  - Assistants respond to prompts — then stop.
  - Agent launchers spin up agents — then you hope they behave.
  - Enterprises hesitate not because models are weak, but because they can't **trust,
    audit, approve, or roll back** AI actions.
  - The missing piece: **accountable work ownership**, not more answers.
- **Suggested visual:** Two columns — "AI that answers" (a chat bubble) vs "AI that owns
  work" (a checklist + approval stamp + audit trail).
- **Speaker notes:** "The blocker to adopting AI for real work isn't capability — it's
  control. You can't put an ungoverned agent near a production system. That's the problem
  ARIA solves."

---

## Slide 3 — What ARIA Is

**Title:** A Governed AI Employee Control Plane

- **Objective:** Define ARIA in one crisp concept.
- **Bullets:**
  - **ARIA is not a chatbot. ARIA is a governed AI employee control plane.**
  - It owns goals, plans work, coordinates agents, learns from work, drafts team
    communication, runs routines, previews controlled actions, and reports ROI.
  - Every step is bounded by permission, evidence, approval, and an audit trail.
- **Suggested visual:** A control-plane diagram: ARIA in the center (governance, memory,
  approval, Work Ledger, policy, ROI) with capability spokes around it.
- **Speaker notes:** "Think of ARIA as the control plane. The model is one component; the
  product is everything around it that makes the model's work reliable, governed, and
  improvable."

---

## Slide 4 — Assistant vs AI Employee

**Title:** An Assistant Answers. ARIA Owns the Work.

- **Objective:** Make the assistant-vs-employee distinction unforgettable.
- **Bullets:**
  - **An assistant answers. ARIA owns a goal, plans work, produces artifacts, asks for
    approval, learns, and reports value.**
  - Assistant: stateless, reactive, no accountability.
  - ARIA: goal-owning, planful, governed, remembered, measured.
- **Suggested visual:** Side-by-side table — Assistant vs ARIA across rows: Input
  (prompt vs goal), Output (answer vs artifacts), Memory (none vs institutional),
  Control (none vs approval gates), Value (none vs ROI).
- **Speaker notes:** "This one line is the whole pitch: an assistant answers; ARIA owns a
  goal, plans the work, produces artifacts, asks for approval, learns, and reports value."

---

## Slide 5 — V3 Capability Map

**Title:** What ARIA V3 Can Do (Ten Governed Subsystems)

- **Objective:** Show breadth at production discipline.
- **Bullets:**
  - Goal Ownership (V3.1) · Work Execution Loop (V3.2)
  - Dynamic Agent Workforce (V3.3) · Agent Supervision + Governance (V3.4)
  - Governed Skill Evolution (V3.5) · Work Memory + World Awareness (V3.6)
  - Draft-only Team Collaboration (V3.7) · Scheduled Routines (V3.8)
  - Controlled Action Gate (V3.9) · Manager Dashboard + ROI (V3.10)
- **Suggested visual:** 10-tile capability grid (2×5), each tile labeled with the
  milestone and a one-word governance tag (e.g. "deny-by-default", "draft-only",
  "fixture-only", "proposal-only").
- **Speaker notes:** "Ten subsystems, all under one governance and audit contract. The
  point isn't one flashy capability — it's breadth held to production discipline."

---

## Slide 6 — End-to-End Flow

**Title:** One Goal, Start to Finish

- **Objective:** Show the single coherent loop.
- **Bullets:**
  - Goal → problem statement → roadmap → task board
  - → specialist agents → evidence/governance → artifacts
  - → approvals → reusable lessons → manager dashboard + ROI
  - Every arrow is a governed transition with a Work Ledger trace.
- **Suggested visual:** Horizontal pipeline diagram with the stages above; a small
  "approval gate" icon before any external-effect stage; a "Work Ledger" rail underneath.
- **Speaker notes:** "This is the loop a vague business goal travels — and we can run it
  end to end, offline, deterministically, in one command. Every transition is audited."

---

## Slide 7 — Governed Agent Workforce

**Title:** It Builds a Team — and Supervises It

- **Objective:** Show multi-agent capability *with* governance.
- **Bullets:**
  - ARIA creates **bounded specialist agents** on demand (typed briefs, narrow scope).
  - It **supervises** them — dependency, budget, quality, escalation gates.
  - It **merges** results and **stops unsafe work** (blocks on missing evidence).
  - Dry-run only: a brief is a plan, never a live process; write tools forbidden.
- **Suggested visual:** Orchestrator node delegating to 3–4 bounded agent nodes; a red
  "STOP" gate on one agent labeled "blocked: missing evidence".
- **Speaker notes:** "It assembles the right specialists for the goal, supervises them,
  and — importantly — stops when evidence is missing instead of fabricating an answer."

---

## Slide 8 — Self-Learning, Safely

**Title:** Learns From Work — Improves Under Approval

- **Objective:** Show self-improvement that is governed, not autonomous.
- **Bullets:**
  - **Work Memory Graph:** reusable, source-cited lessons from real work history.
  - **Skill Evolution:** detects repeated gaps, **proposes** new skills.
  - **Activation is approval-gated** — ARIA never switches on a new capability itself.
  - World awareness is **advisory and fixture-only** — never company truth, never live web.
- **Suggested visual:** "Monitor → Propose → Sandbox → Approve → Activate → Rollback" loop
  with a human checkpoint highlighted at "Approve".
- **Speaker notes:** "It gets better over time — carefully. It proposes; a human approves;
  a safety check gates activation. The important part is not autonomy alone. The important
  part is governed autonomy."

---

## Slide 9 — Team Collaboration

**Title:** Communicates Like a Reliable Teammate — Draft-Only

- **Objective:** Show audience-aware communication that never sends.
- **Bullets:**
  - Prepares manager updates, stakeholder questions, handoff notes, approval-request
    drafts, risk escalations.
  - **Draft-only:** it can draft, summarize, ask, escalate, hand off — it **cannot send,
    post, comment, or email.**
  - Approval marks a draft approved *as an artifact* — it never triggers a send.
- **Suggested visual:** A polished "manager update" draft card with a "DRAFT — not sent"
  watermark and a disabled "Send" button.
- **Speaker notes:** "It writes the update a good colleague would send — but it's a draft.
  Nothing leaves the system. Even an approved draft is not sent."

---

## Slide 10 — Controlled Live Execution

**Title:** The Action Gate — Deny by Default

- **Objective:** Address the #1 concern (real-world actions) head on.
- **Bullets:**
  - Every action: **Preview → Approval → dry-run / internal-mock receipt.**
  - **Deny-by-default:** external targets (Teams/Slack/Jira/GitHub/webhook) are **blocked**
    from execution; live mode is disabled and store-enforced.
  - Approval is **bound to the action + payload + scope** — a changed payload requires
    re-approval; rejected/expired approvals cannot execute.
  - No uncontrolled live writes. Ever.
- **Suggested visual:** A gate diagram: intent → preview → approval → [dry-run ✅ | mock ✅
  | external ❌ blocked | live ❌ disabled] → receipt.
- **Speaker notes:** "Here's the part everyone is right to worry about. ARIA previews the
  action, runs it dry, and the instant it points at a real external system, the gate
  blocks it. Approval is locked to the exact payload."

---

## Slide 11 — Manager Dashboard + ROI

**Title:** Manage It Like an Employee

- **Objective:** Show the single pane of glass + transparent ROI.
- **Bullets:**
  - One read-only view: goals, tasks, agents, memory/skills, drafts, routines, actions,
    **approval queue**, **risks**, and **estimated ROI**.
  - ROI is **estimated, evidence-backed, conservative, transparent** (minutes saved by
    default; cost only if an hourly rate is configured — no invented numbers).
  - The store rejects fabricated claims (e.g. live receipts, non-estimated ROI).
- **Suggested visual:** A dashboard mock with tiles: Goals, Agents, Learning, Drafts,
  Routines, Actions, Approval Queue, Risks, ROI (with an "estimated" badge).
- **Speaker notes:** "This is how you manage it — what it worked on, what it learned, what
  it needs, what it risks, and the value it produced. The ROI is clearly an estimate, with
  the method shown. We don't invent numbers."

---

## Slide 12 — Governance and Safety

**Title:** Governed by Design — Explicit Non-Goals

- **Objective:** State the boundaries plainly; turn "limitations" into trust.
- **Bullets (V3 does NOT include):**
  - No production deployment · no public release
  - No real external writes · no real Teams/Slack/Gmail/Jira/GitHub writes
  - No uncontrolled live browsing · no runtime adapters
  - No Claude Managed Agent integration · no MCP execution
  - No automatic approval · no automatic skill activation
  - No self-modifying production code
- **Suggested visual:** A "Boundaries" panel of crossed-out items (red ✕) next to a green
  "What IS enforced" column (audit, approval, confinement, source-citation).
- **Speaker notes:** "These aren't gaps we forgot — they're deliberate boundaries,
  enforced in code and tests. That discipline is exactly what makes ARIA adoptable."

---

## Slide 13 — Why Not Replaced by Claude Managed Agents

**Title:** Runtimes Are Workers. ARIA Is the Control Plane.

- **Objective:** Pre-empt "doesn't Anthropic already do this?"
- **Bullets:**
  - **Anthropic can provide managed agent runtime. ARIA provides governed work ownership.**
  - **launch-your-agent may create agents quickly. ARIA decides which agents should exist,
    what they are allowed to do, how they are evaluated, and how their work is remembered.**
  - External runtimes (Claude Managed Agents, launch-your-agent, OpenAI Agents SDK, MCP,
    REST/Docker) can become **workers under ARIA** later — they don't replace it.
  - The runtime is swappable; the governance, memory, audit, approval, and ROI layer is
    the moat.
- **Suggested visual:** ARIA as the control plane on top; swappable runtime "workers"
  docked underneath (Claude Managed Agent, OpenAI SDK, MCP, Docker, REST).
- **Speaker notes:** "This is the key strategic point. We can adopt any future runtime
  without giving up control. Anthropic provides the engine; ARIA provides the governed
  work ownership around it."

---

## Slide 14 — What V3 Proves

**Title:** A Practical Governed AI Employee System Is Possible

- **Objective:** Land the credibility with real proof points.
- **Bullets:**
  - V3 focused tests: **371 passed** · Full backend: **1577 passed, 1 skipped**
  - Tag `aria-v3-goal-driven-workforce` → endpoint `17021ef`; merged locally into `master`
  - Deterministic, offline end-to-end proof (one command) — no network, no external write
  - Ten governed subsystems under one audit + policy contract
  - **Public release blocked pending employer/IP approval**
- **Suggested visual:** A "proof bar" with green check badges for each proof point; a
  small lock icon on "public release blocked".
- **Speaker notes:** "This isn't a slide-ware concept. It's built, tested, frozen, tagged,
  and merged — and it runs end to end offline. And it's private until we decide otherwise."

---

## Slide 15 — Next: V4 Roadmap

**Title:** What V4 Can Add (Roadmap — Not Started)

- **Objective:** Show a credible forward path without overpromising.
- **Bullets:**
  - External **runtime adapter layer** — governed backends for real agents.
  - **Claude Managed Agents** adapter · **launch-your-agent** compatibility.
  - **MCP / OpenAI Agents SDK / REST / Docker** agent adapters.
  - **Controlled experiments** + limited approved live execution (behind written policies).
  - Emerging Capability Radar: map new AI launches → adapter proposals.
  - **All gated** on governance, evaluation, and the employer/IP/publication boundary.
- **Suggested visual:** A roadmap arrow from "V3 (governed control plane)" → "V4 (governed
  external runtimes)"; each V4 item tagged "approval-gated".
- **Speaker notes:** "V4 is where external runtimes plug in as governed workers — but
  none of it is started, and all of it stays behind the same governance and approval we
  built in V3."

---

### Appendix — One-line positioning (use anywhere)

- ARIA is not a chatbot. ARIA is a governed AI employee control plane.
- An assistant answers. ARIA owns a goal, plans work, produces artifacts, asks for
  approval, learns, and reports value.
- Anthropic can provide managed agent runtime. ARIA provides governed work ownership.
- launch-your-agent may create agents quickly. ARIA decides which agents should exist,
  what they are allowed to do, how they are evaluated, and how their work is remembered.
- The important part is not autonomy alone. The important part is governed autonomy.

*Cross-references: [`V3_MANAGER_NARRATIVE.md`](V3_MANAGER_NARRATIVE.md),
[`V3_VALUE_PROPOSITION.md`](V3_VALUE_PROPOSITION.md),
[`V3_DEMO_SCRIPT_5_MIN.md`](V3_DEMO_SCRIPT_5_MIN.md),
[`V3_DEMO_TALK_TRACK.md`](V3_DEMO_TALK_TRACK.md),
[`V3_BOUNDARIES_AND_NON_GOALS.md`](V3_BOUNDARIES_AND_NON_GOALS.md),
[`V3_FINAL_ACCEPTANCE_CHECKLIST.md`](V3_FINAL_ACCEPTANCE_CHECKLIST.md).*
