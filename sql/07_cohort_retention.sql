/* =====================================================================================
   07_cohort_retention.sql

   Usage dates are not aligned with lifecycles, so activity-based retention is invalid.
   Retention is measured on lifecycle dates that ARE consistent:
     Subscription retention at day N : end_date IS NULL OR end_date - start_date >= N
                                       eligible if start_date <= snapshot - N
     Account retention at day N      : no churn event within N days of signup
                                       eligible if signup_date <= snapshot - N
   ===================================================================================== */

CREATE OR REPLACE VIEW analytics.v_subscription_retention_windows AS
WITH w(window_days) AS (VALUES (1), (7), (14), (30), (60), (90)),
s AS (
    SELECT sub.*, a.referral_source
    FROM core.subscriptions sub
    INNER JOIN core.accounts a ON a.account_id = sub.account_id
)
SELECT d.dimension, d.segment, w.window_days,
       COUNT(*)                                                                               AS eligible,
       COUNT(*) FILTER (WHERE s.end_date IS NULL OR s.end_date - s.start_date >= w.window_days) AS retained,
       COUNT(*) FILTER (WHERE s.end_date IS NULL OR s.end_date - s.start_date >= w.window_days)::NUMERIC / COUNT(*) AS retention_rate
FROM s
CROSS JOIN w
CROSS JOIN analytics.params p
CROSS JOIN LATERAL (VALUES ('overall', 'All'),
                           ('plan_tier', s.plan_tier),
                           ('billing_frequency', s.billing_frequency),
                           ('referral_source', s.referral_source),
                           ('is_trial', s.is_trial::TEXT),
                           ('start_quarter', TO_CHAR(s.start_date, 'YYYY"Q"Q'))) AS d(dimension, segment)
WHERE s.start_date <= p.snapshot_date - w.window_days
GROUP BY d.dimension, d.segment, w.window_days;

CREATE OR REPLACE VIEW analytics.v_subscription_cohort_retention AS
WITH k AS (SELECT generate_series(0, 12) AS months_since_start),
cohorts AS (
    SELECT start_month AS cohort, COUNT(*) AS cohort_size
    FROM core.subscriptions GROUP BY start_month
)
SELECT c.cohort, c.cohort_size, k.months_since_start,
       COUNT(*) FILTER (WHERE s.end_date IS NULL
                           OR s.end_date >= s.start_date + MAKE_INTERVAL(months => k.months_since_start))::NUMERIC
         / c.cohort_size AS retention_rate
FROM cohorts c
CROSS JOIN k
INNER JOIN core.subscriptions s ON s.start_month = c.cohort
CROSS JOIN analytics.params p
-- only fully observed cells: the last day of the cohort month + k months must be <= snapshot
WHERE (c.cohort + INTERVAL '1 month' - INTERVAL '1 day') + MAKE_INTERVAL(months => k.months_since_start) <= p.snapshot_date
GROUP BY c.cohort, c.cohort_size, k.months_since_start;

CREATE OR REPLACE VIEW analytics.v_account_retention_windows AS
WITH w(window_days) AS (VALUES (30), (60), (90), (180), (365))
SELECT d.dimension, d.segment, w.window_days,
       COUNT(*)                                                                                           AS eligible,
       COUNT(*) FILTER (WHERE af.first_churn_date IS NULL OR af.first_churn_date - af.signup_date >= w.window_days) AS retained,
       COUNT(*) FILTER (WHERE af.first_churn_date IS NULL OR af.first_churn_date - af.signup_date >= w.window_days)::NUMERIC / COUNT(*) AS retention_rate
FROM analytics.account_features af
CROSS JOIN w
CROSS JOIN analytics.params p
CROSS JOIN LATERAL (VALUES ('overall', 'All'),
                           ('signup_quarter', af.signup_quarter),
                           ('referral_source', af.referral_source),
                           ('plan_tier', af.plan_tier),
                           ('breadth_quartile', af.breadth_quartile),
                           ('engagement_segment', af.engagement_segment)) AS d(dimension, segment)
WHERE af.signup_date <= p.snapshot_date - w.window_days
GROUP BY d.dimension, d.segment, w.window_days;

-- name: subscription_retention_windows
SELECT * FROM analytics.v_subscription_retention_windows ORDER BY dimension, segment, window_days;

-- name: subscription_retention_d1_to_d90_overall
-- Conditional aggregation: one row, one column per window
SELECT MAX(retention_rate) FILTER (WHERE window_days = 1)  AS d1,
       MAX(retention_rate) FILTER (WHERE window_days = 7)  AS d7,
       MAX(retention_rate) FILTER (WHERE window_days = 14) AS d14,
       MAX(retention_rate) FILTER (WHERE window_days = 30) AS d30,
       MAX(retention_rate) FILTER (WHERE window_days = 60) AS d60,
       MAX(retention_rate) FILTER (WHERE window_days = 90) AS d90
FROM analytics.v_subscription_retention_windows
WHERE dimension = 'overall';

-- name: cohort_retention_long
SELECT * FROM analytics.v_subscription_cohort_retention ORDER BY cohort, months_since_start;

-- name: cohort_retention_matrix
SELECT cohort, cohort_size,
       MAX(retention_rate) FILTER (WHERE months_since_start = 1)  AS m1,
       MAX(retention_rate) FILTER (WHERE months_since_start = 2)  AS m2,
       MAX(retention_rate) FILTER (WHERE months_since_start = 3)  AS m3,
       MAX(retention_rate) FILTER (WHERE months_since_start = 6)  AS m6,
       MAX(retention_rate) FILTER (WHERE months_since_start = 9)  AS m9,
       MAX(retention_rate) FILTER (WHERE months_since_start = 12) AS m12
FROM analytics.v_subscription_cohort_retention
GROUP BY cohort, cohort_size
ORDER BY cohort;

-- name: cohort_comparison_quarterly
-- Are newer subscription cohorts retaining better? D30/D90 by start quarter, ranked worst first
WITH q AS (
    SELECT segment AS start_quarter,
           MAX(eligible)       FILTER (WHERE window_days = 30) AS eligible_d30,
           MAX(retention_rate) FILTER (WHERE window_days = 30) AS d30,
           MAX(eligible)       FILTER (WHERE window_days = 90) AS eligible_d90,
           MAX(retention_rate) FILTER (WHERE window_days = 90) AS d90
    FROM analytics.v_subscription_retention_windows
    WHERE dimension = 'start_quarter'
    GROUP BY segment
)
SELECT q.*,
       d90 - LAG(d90) OVER (ORDER BY start_quarter)    AS d90_change_vs_prior_quarter,
       RANK() OVER (ORDER BY d90 ASC NULLS LAST)       AS d90_rank_worst_first
FROM q
ORDER BY start_quarter;

-- name: subscription_d90_by_plan_and_channel
SELECT dimension, segment, eligible, retention_rate AS d90_retention,
       retention_rate - AVG(retention_rate) OVER (PARTITION BY dimension) AS gap_vs_dimension_mean
FROM analytics.v_subscription_retention_windows
WHERE window_days = 90 AND dimension IN ('plan_tier', 'referral_source', 'billing_frequency', 'is_trial')
ORDER BY dimension, d90_retention;

-- name: account_retention_windows
SELECT * FROM analytics.v_account_retention_windows ORDER BY dimension, segment, window_days;

-- name: account_retention_by_signup_quarter
SELECT segment AS signup_quarter,
       MAX(retention_rate) FILTER (WHERE window_days = 90)  AS d90,
       MAX(retention_rate) FILTER (WHERE window_days = 180) AS d180,
       MAX(retention_rate) FILTER (WHERE window_days = 365) AS d365,
       MAX(eligible)       FILTER (WHERE window_days = 90)  AS accounts
FROM analytics.v_account_retention_windows
WHERE dimension = 'signup_quarter'
GROUP BY segment
ORDER BY segment;

-- name: retention_by_feature_breadth
-- Does feature adoption relate to retention? (association only)
SELECT af.breadth_quartile,
       COUNT(*)                                   AS accounts,
       MIN(af.distinct_features)                  AS min_features,
       MAX(af.distinct_features)                  AS max_features,
       AVG(af.churn_flag::INT)                    AS churn_rate,
       1 - AVG(af.churn_flag::INT)                AS logo_retention_rate,
       AVG(af.has_churn_event::INT)               AS share_with_churn_event,
       r.retention_rate                           AS account_d180_retention
FROM analytics.account_features af
LEFT JOIN analytics.v_account_retention_windows r
       ON r.dimension = 'breadth_quartile' AND r.segment = af.breadth_quartile AND r.window_days = 180
GROUP BY af.breadth_quartile, r.retention_rate
ORDER BY af.breadth_quartile;
