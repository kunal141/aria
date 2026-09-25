# PR Review Guidelines — Reference Pack

Neutral reference content for the knowledge base. It illustrates the *shape* of review
guidelines an organization would supply; it is not any organization's real policy.
Tenants replace it with their own via a vertical runbook pack, and the services named
in `TenantOrgProfile` take precedence over anything here.

## High-risk changes (block for review)

- Ranking or scoring formula weights
- Ingestion pipeline: parsing, enrichment, indexing
- Notification logic: frequency limits, targeting, content filters
- Schema migrations on large tables
- Experiment assignment logic — incorrect assignment invalidates results
- Authentication or session management
- Analytics event tracking — metric definitions must stay consistent

## Required before merge

- [ ] Unit tests for the changed function or class
- [ ] Integration test for any new API endpoint
- [ ] Performance test when changing a hot path
- [ ] Rollback plan documented in the change description
- [ ] Feature flag for any change affecting user experience at scale

## Deployment risk tiers

- **Tier 1 (Low)** — configuration, copy, non-functional refactors
- **Tier 2 (Medium)** — features behind flags, minor algorithm changes
- **Tier 3 (High)** — model changes, notification logic, schema migrations
- **Tier 4 (Critical)** — authentication, billing, data-deletion pipelines

Tier 3 and Tier 4 require two approvals and a canary deployment before full rollout.

## Ranking / recommendation changes

1. Was a holdout group maintained for the experiment?
2. Are diversity constraints preserved?
3. Is there a feedback-loop risk from reinforcing prior engagement?
4. Was the model evaluated on each significant segment separately, since behaviour differs?

## Notification changes

Check frequency limits and confirm opt-out signals propagate within the declared SLA.

## Analytics pipeline changes

Event schema changes must be backwards compatible:

- Prior event versions still parse
- New fields nullable for a declared transition period
- Downstream queries updated when event names change
