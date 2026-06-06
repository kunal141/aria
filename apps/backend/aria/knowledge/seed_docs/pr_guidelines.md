# PR Review Guidelines — Amar Ujala Engineering

## High-Risk Changes (always block for review)
- Any change to recommendation ranking weights or scoring formula
- Changes to content ingestion pipeline (article parser, enrichment, indexer)
- Notification send logic — frequency limits, targeting rules, content filters
- Database schema migrations on tables with >1M rows
- A/B experiment assignment logic — incorrect assignment = invalid experiment results
- Authentication or session management changes
- Changes to analytics event tracking (CTR, engagement events must be consistent)

## Required Before Any Merge
- [ ] Unit tests for the changed function/class
- [ ] Integration test for any new API endpoint
- [ ] Performance test if changing a hot path (recommendation, feed assembly)
- [ ] Rollback plan documented in PR description
- [ ] Feature flag for any change that affects user experience at scale

## Deployment Risk Tiers
- **Tier 1 (Low)**: Config changes, copy changes, non-functional refactors
- **Tier 2 (Medium)**: New features behind feature flags, minor algorithm changes
- **Tier 3 (High)**: Recommendation model changes, notification logic, schema migrations
- **Tier 4 (Critical)**: Auth changes, billing, data deletion pipelines

Tier 3 and Tier 4 require 2 approvals and a 15-minute canary deployment before full rollout.

## Recommendation Engine PRs
When reviewing recommendation engine PRs, always check:
1. Was a holdout group maintained for the experiment?
2. Are diversity constraints preserved? (≥3 categories in top 10)
3. Is there a feedback loop risk? (e.g., only showing content similar to what was already clicked)
4. Has the model been tested on UP/Delhi regional datasets separately? (engagement patterns differ)

## Notification Service PRs
Check frequency limits: no user should receive >4 notifications/day for non-breaking content.
Check opt-out signal handling — opt-outs must propagate within 60 seconds.

## Analytics Pipeline PRs
Event schema changes must be backwards compatible. Check:
- Old event version still parsed correctly
- New fields are nullable (not required) for at least 2 weeks after launch
- Dashboard queries updated if event names changed
