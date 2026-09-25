/* =====================================================================================
   06_user_segmentation.sql
   Rule-based engagement segments of ACCOUNTS (no user-level table exists).
   Rules are defined once in analytics.account_features (01_schema.sql):
     Power Accounts          total_usage_count >= P75 AND distinct_features >= P75
     Engaged Accounts        not Power AND total_usage_count >= P50
     Casual Accounts         P25 <= total_usage_count < P50
     Low-Engagement Accounts total_usage_count < P25
     high_friction (overlay) error_rate >= P75 OR >= 1 escalated ticket
   ===================================================================================== */

-- name: segment_thresholds
SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p25,
       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p50,
       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p75,
       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY distinct_features) AS breadth_p75,
       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY error_rate)        AS error_rate_p75
FROM analytics.account_features;

-- name: segment_profile
SELECT engagement_segment,
       COUNT(*)                                                                 AS accounts,
       COUNT(*)::NUMERIC / SUM(COUNT(*)) OVER ()                                AS share_of_accounts,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_usage_count)           AS median_usage_count,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY distinct_features)           AS median_distinct_features,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_hours)        AS median_duration_hours,
       AVG(error_rate)                                                          AS mean_error_rate,
       AVG(n_tickets)                                                           AS mean_tickets,
       AVG(high_friction::INT)                                                  AS high_friction_share,
       SUM(mrr_at_snapshot)                                                     AS mrr_at_snapshot,
       SUM(mrr_at_snapshot)::NUMERIC / SUM(SUM(mrr_at_snapshot)) OVER ()        AS share_of_mrr,
       AVG(churn_flag::INT)                                                     AS churn_rate
FROM analytics.account_features
GROUP BY engagement_segment, engagement_segment_order
ORDER BY engagement_segment_order;

-- name: segment_by_plan
SELECT engagement_segment,
       COUNT(*) FILTER (WHERE plan_tier = 'Basic')      AS basic_accounts,
       COUNT(*) FILTER (WHERE plan_tier = 'Pro')        AS pro_accounts,
       COUNT(*) FILTER (WHERE plan_tier = 'Enterprise') AS enterprise_accounts,
       AVG((plan_tier = 'Enterprise')::INT)             AS enterprise_share
FROM analytics.account_features
GROUP BY engagement_segment, engagement_segment_order
ORDER BY engagement_segment_order;

-- name: segment_by_channel
SELECT referral_source,
       COUNT(*)                                                                      AS accounts,
       AVG((engagement_segment IN ('Power Accounts', 'Engaged Accounts'))::INT)      AS engaged_or_better_share,
       AVG((engagement_segment = 'Low-Engagement Accounts')::INT)                    AS low_engagement_share,
       AVG(distinct_features)                                                        AS mean_distinct_features
FROM analytics.account_features
GROUP BY referral_source
ORDER BY engaged_or_better_share DESC;

-- name: segment_friction_churn
SELECT engagement_segment, high_friction,
       COUNT(*)                AS accounts,
       AVG(churn_flag::INT)    AS churn_rate
FROM analytics.account_features
GROUP BY engagement_segment, engagement_segment_order, high_friction
ORDER BY engagement_segment_order, high_friction;

-- name: top_accounts_per_segment
-- Illustrative drill-down: 3 highest-MRR accounts inside each segment
SELECT engagement_segment, account_name, plan_tier, mrr_at_snapshot, total_usage_count, distinct_features, rn AS rank_in_segment
FROM (
    SELECT af.*, ROW_NUMBER() OVER (PARTITION BY engagement_segment ORDER BY mrr_at_snapshot DESC, account_id) AS rn
    FROM analytics.account_features af
) ranked
WHERE rn <= 3
ORDER BY engagement_segment_order, rn;
