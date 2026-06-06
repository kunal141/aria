# Self-Dogfooding Protocol — ARIA Builds ARIA

## What Self-Dogfooding Means

From Week 7 onwards, ARIA uses herself to build herself.

Every time you write code for ARIA, ARIA:
- Reviews the PR on her own codebase
- Generates test cases for the new code
- Documents the architecture decision
- Evaluates her own output quality
- Logs the task in the AI Work Ledger

This means by Week 30, ARIA has done **hundreds of real engineering tasks on a real, production codebase** — her own. No demo data. No synthetic examples. Real work.

---

## The Self-Dogfooding Loop

```
Kunal writes code for ARIA
   ↓
Opens PR on aria/ repository
   ↓
@mentions ARIA in PR description or Teams
   ↓
ARIA reviews the PR (Week 7+ capability)
   Reviews: code quality, deployment risk, missing tests, business impact
   ↓
ARIA generates test cases for the changed code (Week 17+ capability)
   ↓
ARIA documents the architecture decision (if significant) (Week 9+ capability)
   ↓
ARIA logs everything in AI Work Ledger (Week 29+ complete, but basic logging from Week 4)
   ↓
Kunal approves/rejects ARIA's review comments
   ↓
ARIA learns from the approval/rejection pattern (Human Teaching Layer)
   ↓
ARIA improves her next PR review (Skill evolution)
```

---

## Why This Creates an Irreplaceable Moat

| What self-dogfooding creates | Why it's valuable |
|---|---|
| Hundreds of real PR reviews | Training signal on a real engineering codebase |
| Real rejection patterns | ARIA learns what Kunal actually values in code review |
| Real test coverage gaps detected | Proves QA capability on non-trivial code |
| Architecture decisions documented | Growing corpus of technical context |
| ARIA's own bugs found by ARIA | Meta-demonstration of her effectiveness |
| 30-week operational history | Cannot be compressed or manufactured |

A competitor building "ARIA 2.0" starts with zero of this. Your ARIA has months of real work.

---

## What ARIA Reviews on Herself

### Every Code PR
- Code quality assessment (Week 7)
- Business impact explanation (Week 7)
- Deployment risk estimate (Week 7)
- Missing test identification (Week 17)
- Architecture impact (Week 10)

### Every New Skill Added
- Input/output schema review
- Edge cases not covered
- Suggested test cases

### Every Architecture Decision
- Decision context
- Alternatives considered
- Tradeoffs accepted
- Reversibility assessment

### Every Week End
- What capabilities exist now vs last week
- Quality delta (LangSmith rubric scores)
- What improved, what regressed, what's missing

---

## The Meta-Demonstration

The most powerful demo at Week 30:

> "ARIA reviewed 47 of her own PRs during development. Her review comments had a 78% acceptance rate — meaning I, the developer, agreed with 78% of her code review recommendations on her own codebase. Her test case suggestions caught 3 real bugs that I had missed."

This is not a benchmarked demo. This is operational proof on a real system.

---

## Starting Self-Dogfooding (Week 7)

**Prerequisites**: PR review skill exists (Week 7), Teams bot live (Week 13)

**Setup**:
1. ARIA is added as a reviewer on the `aria/` GitHub repo
2. Every PR automatically sends a webhook to ARIA's review endpoint
3. ARIA posts her review as a GitHub comment within 2 minutes
4. Kunal approves/rejects comments — all signals logged
5. After 5 reviews, check LangSmith traces — are reviews improving?

**What to track in the AI Work Ledger**:
- PR ID + title
- ARIA's review comments (full text)
- Which comments Kunal approved/rejected/modified
- Whether ARIA flagged any real issues (test: were there actual bugs?)
- Time from PR open to ARIA review (latency metric)
- Review quality rubric score

---

## Self-Dogfooding Log Template

Add to learning journal after each week:

```markdown
## Week [X] Self-Dogfooding Log

PRs reviewed by ARIA this week: [N]
Comments posted: [N]
Comments accepted by Kunal: [N] ([%] acceptance rate)
Real bugs/issues caught: [N]
Most common rejection reason: [reason]
Learning applied next week: [what ARIA changed based on feedback]
```
