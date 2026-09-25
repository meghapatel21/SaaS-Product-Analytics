/* =====================================================================================
   05_feature_adoption.sql
   Adoption rate (feature) = accounts with >= 1 usage event of the feature / all accounts
   ===================================================================================== */

CREATE OR REPLACE VIEW analytics.v_feature_usage_enriched AS
SELECT u.usage_row_id, u.usage_id, u.subscription_id, s.account_id,
       u.usage_date, u.usage_month, u.feature_name, u.usage_count, u.usage_duration_secs,
       u.error_count, u.is_beta_feature, u.is_in_subscription_window,
       s.plan_tier  AS subscription_plan_tier,
       af.plan_tier AS account_plan_tier,
       af.industry, af.referral_source, af.engagement_segment, af.churn_flag
FROM core.feature_usage u
INNER JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
INNER JOIN analytics.account_features af ON af.account_id = s.account_id;

CREATE OR REPLACE VIEW analytics.v_feature_summary AS
WITH f AS (
    SELECT feature_name,
           COUNT(DISTINCT account_id)     AS adopting_accounts,
           COUNT(*)                       AS usage_events,
           SUM(usage_count)               AS total_usage_count,
           SUM(usage_duration_secs)       AS total_duration_secs,
           SUM(error_count)               AS total_errors,
           AVG(is_beta_feature::INT)      AS beta_event_share
    FROM analytics.v_feature_usage_enriched
    GROUP BY feature_name
),
m AS (
    SELECT f.*,
           f.adopting_accounts::NUMERIC / (SELECT COUNT(*) FROM core.accounts) AS adoption_rate,
           f.total_usage_count::NUMERIC / f.adopting_accounts                  AS usage_count_per_adopting_account
    FROM f
),
med AS (
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY adoption_rate)                    AS med_adoption,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY usage_count_per_adopting_account) AS med_intensity
    FROM m
)
SELECT m.feature_name, m.adopting_accounts, m.adoption_rate, m.usage_events,
       m.usage_events::NUMERIC / m.adopting_accounts                 AS events_per_adopting_account,
       m.usage_count_per_adopting_account,
       m.total_duration_secs / 60.0 / m.usage_events                 AS avg_minutes_per_event,
       100.0 * m.total_errors / NULLIF(m.total_usage_count, 0)       AS errors_per_100_uses,
       m.beta_event_share,
       RANK() OVER (ORDER BY m.adopting_accounts DESC)               AS adoption_rank,
       CASE WHEN m.adoption_rate >= med.med_adoption AND m.usage_count_per_adopting_account >= med.med_intensity THEN 'Core (broad & intensive)'
            WHEN m.adoption_rate <  med.med_adoption AND m.usage_count_per_adopting_account >= med.med_intensity THEN 'Underutilized (narrow but intensive)'
            WHEN m.adoption_rate >= med.med_adoption THEN 'Broad but light'
            ELSE 'Low traction' END                                  AS adoption_quadrant
FROM m CROSS JOIN med;

-- name: feature_summary
SELECT * FROM analytics.v_feature_summary ORDER BY adoption_rank, feature_name;

-- name: feature_top_bottom
WITH ranked AS (
    SELECT feature_name, adopting_accounts, adoption_rate, errors_per_100_uses,
           ROW_NUMBER() OVER (ORDER BY adopting_accounts DESC, feature_name) AS top_rn,
           ROW_NUMBER() OVER (ORDER BY adopting_accounts ASC, feature_name)  AS bottom_rn
    FROM analytics.v_feature_summary
)
SELECT CASE WHEN top_rn <= 5 THEN 'Most adopted' ELSE 'Least adopted' END AS list,
       feature_name, adopting_accounts, adoption_rate, errors_per_100_uses
FROM ranked
WHERE top_rn <= 5 OR bottom_rn <= 5
ORDER BY list DESC, adopting_accounts DESC;

-- name: feature_adoption_by_plan
-- Within-plan adoption: accounts using the feature on a subscription of that tier /
-- accounts with any usage on that tier (conditional aggregation pivot)
WITH base AS (
    SELECT subscription_plan_tier, COUNT(DISTINCT account_id) AS accounts_with_usage
    FROM analytics.v_feature_usage_enriched GROUP BY subscription_plan_tier
),
used AS (
    SELECT subscription_plan_tier, feature_name, COUNT(DISTINCT account_id) AS accounts
    FROM analytics.v_feature_usage_enriched GROUP BY subscription_plan_tier, feature_name
),
rates AS (
    SELECT u.feature_name, u.subscription_plan_tier, u.accounts::NUMERIC / b.accounts_with_usage AS adoption_rate
    FROM used u JOIN base b USING (subscription_plan_tier)
)
SELECT feature_name,
       MAX(adoption_rate) FILTER (WHERE subscription_plan_tier = 'Basic')      AS basic,
       MAX(adoption_rate) FILTER (WHERE subscription_plan_tier = 'Pro')        AS pro,
       MAX(adoption_rate) FILTER (WHERE subscription_plan_tier = 'Enterprise') AS enterprise,
       MAX(adoption_rate) - MIN(adoption_rate)                                 AS max_plan_gap
FROM rates
GROUP BY feature_name
ORDER BY max_plan_gap DESC;

-- name: plan_usage_profile
SELECT s.plan_tier,
       COUNT(DISTINCT s.subscription_id)                                    AS subscriptions,
       COUNT(u.usage_row_id)                                                AS usage_events,
       COUNT(u.usage_row_id)::NUMERIC / COUNT(DISTINCT s.subscription_id)   AS events_per_subscription,
       AVG(u.usage_duration_secs) / 60.0                                    AS avg_minutes_per_event,
       100.0 * SUM(u.error_count) / NULLIF(SUM(u.usage_count), 0)           AS errors_per_100_uses
FROM core.subscriptions s
LEFT JOIN core.feature_usage u ON u.subscription_id = s.subscription_id   -- keep subscriptions with no usage (33)
GROUP BY s.plan_tier
ORDER BY CASE s.plan_tier WHEN 'Basic' THEN 1 WHEN 'Pro' THEN 2 ELSE 3 END;

-- name: beta_vs_ga_usage
SELECT is_beta_feature,
       COUNT(*)                                                 AS usage_events,
       AVG(usage_count)                                         AS mean_usage_count,
       AVG(usage_duration_secs) / 60.0                          AS mean_minutes,
       AVG(error_count)                                         AS mean_errors_per_event,
       AVG((error_count > 0)::INT)                              AS share_events_with_error,
       100.0 * SUM(error_count) / NULLIF(SUM(usage_count), 0)   AS errors_per_100_uses
FROM core.feature_usage
GROUP BY is_beta_feature;

-- name: feature_usage_quarterly
WITH q AS (
    SELECT DATE_TRUNC('quarter', usage_date)::DATE AS quarter, feature_name,
           COUNT(*) AS usage_events, COUNT(DISTINCT account_id) AS accounts
    FROM analytics.v_feature_usage_enriched
    GROUP BY 1, 2
)
SELECT quarter, feature_name, usage_events, accounts,
       usage_events::NUMERIC / SUM(usage_events) OVER (PARTITION BY quarter)                 AS share_of_quarter_events,
       usage_events - LAG(usage_events) OVER (PARTITION BY feature_name ORDER BY quarter)    AS qoq_event_change,
       RANK() OVER (PARTITION BY quarter ORDER BY usage_events DESC)                         AS rank_in_quarter
FROM q
ORDER BY quarter, rank_in_quarter;

-- name: feature_adoption_by_engagement_segment
WITH base AS (
    SELECT engagement_segment, COUNT(DISTINCT account_id) AS accounts
    FROM analytics.account_features GROUP BY engagement_segment
)
SELECT e.engagement_segment, e.feature_name,
       COUNT(DISTINCT e.account_id)::NUMERIC / b.accounts AS adoption_rate
FROM analytics.v_feature_usage_enriched e
JOIN base b ON b.engagement_segment = e.engagement_segment
GROUP BY e.engagement_segment, e.feature_name, b.accounts
ORDER BY e.engagement_segment, adoption_rate DESC;
