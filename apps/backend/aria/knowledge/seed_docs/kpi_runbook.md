# KPI Investigation Runbook — Reference Pack

Neutral reference content for the knowledge base. It illustrates the *shape* of a
runbook an organization would supply; it is not any organization's real operating
policy. Tenants replace it with their own via a vertical runbook pack, and the
metrics/services named in `TenantOrgProfile` take precedence over anything here.

## Engagement-metric drop investigation

When a primary engagement metric (for example click-through rate) drops materially
week-on-week:

1. Establish whether the drop is global or segment-specific before investigating cause.
2. Pull item-level performance for the top entities and identify affected categories.
3. Check whether a ranking or recommendation model version deployed in the change window.
4. Verify ingestion-pipeline health — new items should appear within the declared SLA.
5. Check notification volume and open rate; a send spike can suppress engagement.
6. Review experiment assignments and confirm the holdout group is stable.

Common causes:

- A ranking-model weight change altering result diversity.
- Ingestion lag serving stale items as fresh.
- A client release changing layout or tap-target size.
- Category mix shift changing the denominator rather than the behaviour.
- Notification fatigue causing dismissal without engagement.

## Feed freshness

Define a freshness SLA (for example: top items under N hours old during peak windows).
If freshness degrades:

1. Check the pipeline status dashboard for ingestion lag.
2. Check indexer queue depth for backlog.
3. Check cache TTL — an over-long TTL serves stale items from cache.

## Investigation discipline

- State whether the change is statistically meaningful before attributing a cause.
- Separate what the evidence shows from what it merely suggests.
- If the data does not support a conclusion, say so and name the missing evidence
  rather than asserting a cause.
