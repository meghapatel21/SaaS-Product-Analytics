/* =====================================================================================
   09_business_insights.sql  -  queries that back each insight in docs/BUSINESS_INSIGHTS.md
   All results are observational associations.
   ===================================================================================== */

-- name: insight_1_trial_funnel_bottleneck
SELECT stage, accounts, step_conversion, step_drop_off,
       RANK() OVER (ORDER BY step_drop_off DESC NULLS LAST) AS drop_off_rank
FROM analytics.v_funnel_stage_counts
WHERE dimension = 'overall' AND funnel = 'trial'
ORDER BY stage_order;

-- name: insight_2_channel_churn_and_revenue
WITH post_trial AS (
    SELECT segment AS referral_source,
           MAX(step_conversion) FILTER (WHERE stage_order = 4) AS converted_to_retained_rate
    FROM analytics.v_funnel_stage_counts
    WHERE funnel = 'trial' AND dimension = 'referral_source'
    GROUP BY segment
)
SELECT af.referral_source,
       COUNT(*)                                                         AS accounts,
       AVG(af.churn_flag::INT)                                          AS churn_rate,
       pt.converted_to_retained_rate,
       SUM(af.mrr_at_snapshot)                                          AS mrr_at_snapshot,
       SUM(af.mrr_at_snapshot)::NUMERIC / SUM(SUM(af.mrr_at_snapshot)) OVER () AS mrr_share,
       RANK() OVER (ORDER BY AVG(af.churn_flag::INT))                   AS lowest_churn_rank
FROM analytics.account_features af
LEFT JOIN post_trial pt ON pt.referral_source = af.referral_source
GROUP BY af.referral_source, pt.converted_to_retained_rate
ORDER BY churn_rate;

-- name: insight_3_industry_churn
SELECT industry,
       COUNT(*)                                                         AS accounts,
       COUNT(*) FILTER (WHERE churn_flag)                               AS churned,
       AVG(churn_flag::INT)                                             AS churn_rate,
       SUM(mrr_at_snapshot)::NUMERIC / SUM(SUM(mrr_at_snapshot)) OVER () AS mrr_share
FROM analytics.account_features
GROUP BY industry
ORDER BY churn_rate DESC;

-- name: insight_4_engagement_vs_churn
SELECT CASE WHEN engagement_segment IN ('Power Accounts', 'Engaged Accounts') THEN 'High engagement' ELSE 'Low engagement' END AS engagement_group,
       CASE WHEN distinct_features >= (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY distinct_features) FROM analytics.account_features)
            THEN 'Broad adopter' ELSE 'Narrow adopter' END AS breadth_group,
       COUNT(*)                AS accounts,
       AVG(churn_flag::INT)    AS churn_rate
FROM analytics.account_features
GROUP BY GROUPING SETS ((1), (2))
ORDER BY 1, 2;

-- name: insight_5_revenue_concentration_by_plan
WITH plan_mrr AS (
    SELECT plan_tier, COUNT(*) AS active_subscriptions, SUM(mrr_amount) AS mrr
    FROM core.subscriptions WHERE end_date IS NULL GROUP BY plan_tier
),
plan_churn AS (
    SELECT plan_tier, AVG(churn_flag::INT) AS account_churn_rate FROM core.accounts GROUP BY plan_tier
)
SELECT m.plan_tier, m.active_subscriptions,
       m.active_subscriptions::NUMERIC / SUM(m.active_subscriptions) OVER () AS subscription_share,
       m.mrr, m.mrr::NUMERIC / SUM(m.mrr) OVER ()                            AS mrr_share,
       c.account_churn_rate
FROM plan_mrr m
INNER JOIN plan_churn c ON c.plan_tier = m.plan_tier
ORDER BY m.mrr DESC;

-- name: insight_6_feature_adoption_spread
SELECT MIN(adoption_rate)                                                   AS min_adoption_rate,
       MAX(adoption_rate)                                                   AS max_adoption_rate,
       STDDEV_SAMP(adoption_rate)                                           AS sd_adoption_rate,
       COUNT(*) FILTER (WHERE adoption_quadrant LIKE 'Underutilized%')      AS underutilized_features,
       (SELECT AVG(error_count) FROM core.feature_usage WHERE is_beta_feature)     AS beta_errors_per_event,
       (SELECT AVG(error_count) FROM core.feature_usage WHERE NOT is_beta_feature) AS ga_errors_per_event
FROM analytics.v_feature_summary;

-- name: insight_7_support_priority
SELECT priority,
       COUNT(*)                          AS tickets,
       AVG(resolution_time_hours)        AS avg_resolution_hours,
       AVG(escalation_flag::INT)         AS escalation_rate,
       AVG(satisfaction_score)           AS avg_csat,
       AVG(resolution_time_hours) - AVG(AVG(resolution_time_hours)) OVER () AS gap_vs_mean_hours
FROM core.support_tickets
GROUP BY priority
ORDER BY CASE priority WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;

-- name: insight_8_data_integrity
SELECT (SELECT COUNT(*) FROM core.accounts WHERE dq_churn_flag_conflict)                    AS accounts_churn_source_conflict,
       (SELECT COUNT(*) FROM analytics.account_features WHERE churn_flag AND n_active_subscriptions > 0) AS churned_accounts_with_active_subscriptions,
       (SELECT SUM(mrr_at_snapshot) FROM analytics.account_features WHERE churn_flag)        AS mrr_on_churned_accounts,
       (SELECT AVG(dq_before_account_signup::INT) FROM core.feature_usage)                   AS usage_before_signup_share,
       (SELECT AVG(dq_before_account_signup::INT) FROM core.support_tickets)                 AS tickets_before_signup_share;

-- name: insight_9_churn_event_intensity
WITH q AS (
    SELECT DATE_TRUNC('quarter', churn_date)::DATE AS quarter, COUNT(*) AS churn_events
    FROM analytics.v_churn_events
    GROUP BY 1
)
SELECT q.quarter, q.churn_events,
       COUNT(a.account_id)                               AS accounts_signed_up_by_quarter_end,
       100.0 * q.churn_events / COUNT(a.account_id)      AS churn_events_per_100_accounts
FROM q
LEFT JOIN core.accounts a
       ON a.signup_date <= (q.quarter + INTERVAL '3 months' - INTERVAL '1 day')
GROUP BY q.quarter, q.churn_events
ORDER BY q.quarter;
