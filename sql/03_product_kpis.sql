/* =====================================================================================
   03_product_kpis.sql  -  SaaS KPIs (definitions: docs/ANALYSIS_PLAN.md)

   Active subscription at date d: start_date <= d AND (end_date IS NULL OR end_date > d)
   MRR at d:                      SUM(mrr_amount) over subscriptions active at d
   Monthly churn rates:           ended during month / active at end of previous month
   ===================================================================================== */

CREATE OR REPLACE VIEW analytics.v_kpi_monthly AS
WITH months AS (
    SELECT gs::DATE                                          AS month_start,
           (gs + INTERVAL '1 month' - INTERVAL '1 day')::DATE AS month_end
    FROM generate_series(DATE '2023-01-01', DATE '2024-12-01', INTERVAL '1 month') AS gs
),
active AS (          -- subscriptions active at month end
    SELECT m.month_start,
           COUNT(s.subscription_id)                                    AS active_subscriptions,
           COUNT(DISTINCT s.account_id) FILTER (WHERE NOT s.is_trial)  AS paying_accounts,
           COALESCE(SUM(s.seats) FILTER (WHERE NOT s.is_trial), 0)     AS paid_seats,
           COALESCE(SUM(s.mrr_amount), 0)                              AS mrr
    FROM months m
    LEFT JOIN core.subscriptions s
           ON s.start_date <= m.month_end
          AND (s.end_date IS NULL OR s.end_date > m.month_end)
    GROUP BY m.month_start
),
base AS (            -- start-of-month base = active at end of previous month
    SELECT m.month_start,
           COUNT(s.subscription_id)                                                                  AS start_of_month_subscriptions,
           COALESCE(SUM(s.mrr_amount), 0)                                                            AS start_of_month_mrr,
           COUNT(s.subscription_id) FILTER (WHERE s.end_date BETWEEN m.month_start AND m.month_end)  AS ended_subscriptions_from_base,
           COALESCE(SUM(s.mrr_amount) FILTER (WHERE s.end_date BETWEEN m.month_start AND m.month_end), 0) AS churned_mrr_from_base
    FROM months m
    LEFT JOIN core.subscriptions s
           ON s.start_date <= m.month_start - 1
          AND (s.end_date IS NULL OR s.end_date > m.month_start - 1)
    GROUP BY m.month_start
),
new_accounts AS (
    SELECT signup_month AS month_start, COUNT(*) AS new_accounts
    FROM core.accounts GROUP BY signup_month
),
new_subs AS (
    SELECT start_month AS month_start, COUNT(*) AS new_subscriptions, SUM(mrr_amount) AS new_subscription_mrr
    FROM core.subscriptions GROUP BY start_month
),
churn AS (
    SELECT churn_month AS month_start, COUNT(*) AS churn_events
    FROM core.churn_events WHERE NOT dq_duplicate_account_date GROUP BY churn_month
)
SELECT m.month_start                                                         AS month,
       COALESCE(na.new_accounts, 0)                                          AS new_accounts,
       SUM(COALESCE(na.new_accounts, 0)) OVER (ORDER BY m.month_start)       AS cumulative_accounts,
       COALESCE(ns.new_subscriptions, 0)                                     AS new_subscriptions,
       COALESCE(ns.new_subscription_mrr, 0)                                  AS new_subscription_mrr,
       a.active_subscriptions,
       a.paying_accounts,
       a.paid_seats,
       a.mrr,
       a.mrr * 12                                                            AS arr,
       a.mrr::NUMERIC / NULLIF(a.paying_accounts, 0)                         AS arpa,
       a.mrr::NUMERIC / NULLIF(a.paid_seats, 0)                              AS revenue_per_paid_seat,
       a.mrr - LAG(a.mrr) OVER (ORDER BY m.month_start)                      AS mrr_change,
       a.mrr::NUMERIC / NULLIF(LAG(a.mrr) OVER (ORDER BY m.month_start), 0) - 1 AS mrr_growth_rate,
       b.start_of_month_subscriptions,
       b.ended_subscriptions_from_base,
       b.ended_subscriptions_from_base::NUMERIC / NULLIF(b.start_of_month_subscriptions, 0) AS subscription_churn_rate,
       b.start_of_month_mrr,
       b.churned_mrr_from_base,
       b.churned_mrr_from_base::NUMERIC / NULLIF(b.start_of_month_mrr, 0)   AS gross_mrr_churn_rate,
       COALESCE(c.churn_events, 0)                                           AS churn_events
FROM months m
JOIN active a        ON a.month_start  = m.month_start
JOIN base b          ON b.month_start  = m.month_start
LEFT JOIN new_accounts na ON na.month_start = m.month_start
LEFT JOIN new_subs ns     ON ns.month_start = m.month_start
LEFT JOIN churn c         ON c.month_start  = m.month_start;

-- name: kpi_snapshot
WITH active AS (
    SELECT * FROM core.subscriptions WHERE end_date IS NULL
),
af AS (
    SELECT * FROM analytics.account_features
),
feature_adoption AS (
    SELECT feature_name, COUNT(DISTINCT s.account_id)::NUMERIC / (SELECT COUNT(*) FROM core.accounts) AS adoption_rate
    FROM core.feature_usage u JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
    GROUP BY feature_name
)
SELECT
    (SELECT COUNT(*) FROM core.accounts)                                                        AS total_accounts,
    (SELECT COUNT(*) FROM core.accounts WHERE EXTRACT(YEAR FROM signup_date) = 2023)            AS new_accounts_2023,
    (SELECT COUNT(*) FROM core.accounts WHERE EXTRACT(YEAR FROM signup_date) = 2024)            AS new_accounts_2024,
    (SELECT COUNT(*) FROM active)                                                               AS active_subscriptions_at_snapshot,
    (SELECT SUM(mrr_amount) FROM active)                                                        AS mrr_at_snapshot,
    (SELECT SUM(arr_amount) FROM active)                                                        AS arr_at_snapshot,
    (SELECT SUM(mrr_amount)::NUMERIC / COUNT(DISTINCT account_id) FILTER (WHERE NOT is_trial) FROM active) AS arpa,
    (SELECT SUM(mrr_amount)::NUMERIC / SUM(seats) FILTER (WHERE NOT is_trial) FROM active)      AS revenue_per_paid_seat,
    (SELECT COUNT(*) FILTER (WHERE has_trial_subscription) FROM af)                             AS trial_accounts,
    (SELECT AVG(trial_converted::INT) FROM af WHERE has_trial_subscription)                     AS trial_to_paid_conversion_rate,
    (SELECT AVG(churn_flag::INT) FROM core.accounts)                                            AS account_churn_rate,
    (SELECT 1 - AVG(churn_flag::INT) FROM core.accounts)                                        AS logo_retention_rate,
    (SELECT AVG(has_churn_event::INT) FROM core.accounts)                                       AS accounts_with_churn_event_rate,
    (SELECT AVG(is_reactivation::INT) FROM core.churn_events WHERE NOT dq_duplicate_account_date) AS reactivation_share,
    (SELECT AVG(churn_flag::INT) FROM core.subscriptions)                                       AS lifetime_subscription_churn_rate,
    (SELECT AVG(subscription_churn_rate) FROM analytics.v_kpi_monthly WHERE EXTRACT(YEAR FROM month) = 2024) AS avg_monthly_subscription_churn_2024,
    (SELECT AVG(gross_mrr_churn_rate) FROM analytics.v_kpi_monthly WHERE EXTRACT(YEAR FROM month) = 2024)    AS avg_monthly_gross_mrr_churn_2024,
    (SELECT AVG(upgrade_flag::INT) FROM core.subscriptions)                                     AS subscription_upgrade_rate,
    (SELECT AVG(downgrade_flag::INT) FROM core.subscriptions)                                   AS subscription_downgrade_rate,
    (SELECT AVG(adoption_rate) FROM feature_adoption)                                           AS mean_feature_adoption_rate,
    (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY distinct_features) FROM af)             AS median_distinct_features,
    (SELECT COUNT(*)::NUMERIC FROM core.support_tickets) / (SELECT COUNT(*) FROM core.accounts) AS tickets_per_account,
    (SELECT AVG(escalation_flag::INT) FROM core.support_tickets)                                AS escalation_rate,
    (SELECT AVG(has_satisfaction_response::INT) FROM core.support_tickets)                      AS csat_response_rate,
    (SELECT AVG(satisfaction_score) FROM core.support_tickets)                                  AS avg_csat,
    (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY resolution_time_hours) FROM core.support_tickets) AS median_resolution_hours,
    (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY first_response_time_minutes)
       FROM core.support_tickets WHERE NOT dq_first_response_after_resolution)                  AS median_first_response_minutes;

-- name: kpi_monthly
SELECT * FROM analytics.v_kpi_monthly ORDER BY month;

-- name: kpi_mrr_by_plan_snapshot
SELECT plan_tier,
       COUNT(*)                                                   AS active_subscriptions,
       COUNT(DISTINCT account_id)                                 AS accounts,
       SUM(seats)                                                 AS seats,
       SUM(mrr_amount)                                            AS mrr,
       SUM(mrr_amount)::NUMERIC / SUM(SUM(mrr_amount)) OVER ()    AS mrr_share,
       COUNT(*) FILTER (WHERE is_trial)                           AS trial_subscriptions,
       RANK() OVER (ORDER BY SUM(mrr_amount) DESC)                AS mrr_rank
FROM core.subscriptions
WHERE end_date IS NULL
GROUP BY plan_tier
ORDER BY mrr_rank;

-- name: kpi_mrr_by_channel_snapshot
-- INNER JOIN: only accounts that hold active subscriptions contribute MRR
SELECT a.referral_source,
       COUNT(DISTINCT a.account_id)                                          AS accounts,
       SUM(s.mrr_amount)                                                     AS mrr,
       SUM(s.mrr_amount)::NUMERIC / COUNT(DISTINCT a.account_id)             AS mrr_per_account,
       SUM(s.mrr_amount)::NUMERIC / SUM(SUM(s.mrr_amount)) OVER ()           AS mrr_share,
       DENSE_RANK() OVER (ORDER BY SUM(s.mrr_amount) DESC)                   AS mrr_rank
FROM core.accounts a
INNER JOIN core.subscriptions s ON s.account_id = a.account_id AND s.end_date IS NULL
GROUP BY a.referral_source
ORDER BY mrr_rank;

-- name: kpi_mrr_growth_quarterly
WITH q AS (
    SELECT DATE_TRUNC('quarter', month)::DATE AS quarter,
           MAX(month)                         AS last_month
    FROM analytics.v_kpi_monthly
    GROUP BY 1
)
SELECT q.quarter,
       k.mrr                                                            AS quarter_end_mrr,
       k.paying_accounts,
       k.arpa,
       k.mrr::NUMERIC / NULLIF(LAG(k.mrr) OVER (ORDER BY q.quarter), 0) - 1 AS qoq_mrr_growth
FROM q
JOIN analytics.v_kpi_monthly k ON k.month = q.last_month
ORDER BY q.quarter;

-- name: kpi_support_by_priority
SELECT priority,
       COUNT(*)                                                          AS tickets,
       AVG(resolution_time_hours)                                        AS avg_resolution_hours,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY first_response_time_minutes)
           FILTER (WHERE NOT dq_first_response_after_resolution)         AS median_first_response_minutes,
       AVG(escalation_flag::INT)                                         AS escalation_rate,
       AVG(has_satisfaction_response::INT)                               AS csat_response_rate,
       AVG(satisfaction_score)                                           AS avg_csat
FROM core.support_tickets
GROUP BY priority
ORDER BY CASE priority WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 ELSE 4 END;
