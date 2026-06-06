# KPI Investigation Runbook — Amar Ujala

## CTR Drop Investigation
When homepage CTR drops >10% week-on-week:
1. Check if the drop is global or segment-specific (UP vs Delhi vs National)
2. Pull article-level CTR for top 20 stories — identify if specific content categories are affected
3. Check recommendation model version deployed in the past 72 hours (model_deployment_log table)
4. Verify content ingestion pipeline health — articles should appear within 15 minutes of publish
5. Check notification send volume and open rates — a spike in notifications can cause CTR fatigue
6. Review A/B experiment assignments — ensure holdout group is stable

Common CTR drop causes:
- Recommendation model weight change affecting content diversity
- Ingestion lag causing stale content in feed (articles >4 hours old shown as fresh)
- App release introducing UI change that affected tap target size
- Content category mix shift (e.g., politics-heavy day reduces entertainment CTR)
- Notification overload causing users to dismiss feed without reading

## Feed Performance
Feed freshness SLA: top 10 articles in the feed should be <2 hours old during peak hours (7am-11am IST, 6pm-10pm IST).
If freshness drops:
1. Check content_pipeline_status dashboard for ingestion lag
2. Check indexer queue depth — if >500 pending, indexing is backed up
3. Check Redis cache TTL — if TTL is too long, stale articles are served from cache

## Notification CTR
Baseline notification open rate: 12-18% (varies by content category)
- Breaking news: 22-28%
- Sports: 18-24%
- Entertainment: 10-14%
- Business: 8-12%

If open rate drops >20% from baseline, check:
1. Notification send frequency — if >3 per day per user, fatigue sets in
2. Title quality — notifications should be specific, not clickbait
3. Timing — notifications sent between 9pm-7am IST have 40% lower open rate
4. Device segment — Android vs iOS performance differs significantly

## Recommendation Engine
Model: collaborative filtering + content-based hybrid, retrained weekly on Sundays 2am IST
Diversity target: top 10 recommended articles should span ≥3 content categories
Recency target: ≥60% of recommended articles should be <6 hours old during peak hours

Signals used: article_clicks, time_on_page, scroll_depth, share_events, notification_clicks
