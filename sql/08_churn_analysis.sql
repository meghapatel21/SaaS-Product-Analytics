/* =====================================================================================
   08_churn_analysis.sql  -  Churn drivers (observational: "associated with", not "causes")
   Account churn label : accounts.churn_flag
   Churn reasons/timing: churn_events (repeated account+date event excluded)
   ===================================================================================== */

CREATE OR REPLACE VIEW analytics.v_churn_by_segment AS
WITH overall AS (
    SELECT AVG(churn_flag::INT) AS overall_churn_rate FROM analytics.account_features
),
long AS (
    SELECT d.dimension, d.segment, af.churn_flag
    FROM analytics.account_features af
    CROSS JOIN LATERAL (VALUES
        ('plan_tier', af.plan_tier),
        ('highest_plan_tier', af.highest_plan_tier),
        ('industry', af.industry),
        ('country', af.country),
        ('referral_source', af.referral_source),
        ('signup_quarter', af.signup_quarter),
        ('tenure_bucket', af.tenure_bucket),
        ('engagement_segment', af.engagement_segment),
        ('breadth_quartile', af.breadth_quartile),
        ('usage_quartile', af.usage_quartile),
        ('ticket_bucket', af.ticket_bucket),
        ('any_escalation', af.any_escalation::TEXT),
        ('high_friction', af.high_friction::TEXT),
        ('is_trial', af.is_trial::TEXT),
        ('has_trial_subscription', af.has_trial_subscription::TEXT),
        ('any_upgrade', af.any_upgrade::TEXT),
        ('any_downgrade', af.any_downgrade::TEXT)
    ) AS d(dimension, segment)
)
SELECT l.dimension, l.segment,
       COUNT(*)                                          AS accounts,
       COUNT(*) FILTER (WHERE l.churn_flag)              AS churned,
       AVG(l.churn_flag::INT)                            AS churn_rate,
       AVG(l.churn_flag::INT) / o.overall_churn_rate     AS lift_vs_overall
FROM long l
CROSS JOIN overall o
GROUP BY l.dimension, l.segment, o.overall_churn_rate;

CREATE OR REPLACE VIEW analytics.v_churn_events AS
SELECT c.churn_event_id, c.account_id, c.churn_date, c.churn_month, c.reason_code, c.refund_amount_usd,
       c.preceding_upgrade_flag, c.preceding_downgrade_flag, c.is_reactivation, c.feedback_text,
       a.plan_tier, a.industry, a.referral_source, a.engagement_segment,
       a.churn_flag AS account_churn_flag,
       c.churn_date - a.signup_date AS days_since_signup
FROM core.churn_events c
INNER JOIN analytics.account_features a ON a.account_id = c.account_id
WHERE NOT c.dq_duplicate_account_date;

-- name: churn_overall
SELECT (SELECT COUNT(*) FROM core.accounts)                          AS accounts,
       (SELECT COUNT(*) FILTER (WHERE churn_flag) FROM core.accounts) AS churned_accounts,
       (SELECT AVG(churn_flag::INT) FROM core.accounts)              AS account_churn_rate,
       (SELECT AVG(has_churn_event::INT) FROM core.accounts)         AS accounts_with_churn_event_rate,
       (SELECT COUNT(*) FROM analytics.v_churn_events)               AS churn_events,
       (SELECT AVG(churn_flag::INT) FROM core.subscriptions)         AS subscription_churn_rate;

-- name: churn_by_segment
SELECT * FROM analytics.v_churn_by_segment ORDER BY dimension, churn_rate DESC;

-- name: churn_highest_lift_segments
-- Segments with >= 30 accounts ranked by churn lift (small groups excluded to limit noise)
SELECT dimension, segment, accounts, churned, churn_rate, lift_vs_overall,
       RANK() OVER (ORDER BY lift_vs_overall DESC) AS lift_rank
FROM analytics.v_churn_by_segment
WHERE accounts >= 30
ORDER BY lift_rank
LIMIT 12;

-- name: churn_reasons
SELECT reason_code,
       COUNT(*)                                        AS events,
       COUNT(DISTINCT account_id)                      AS accounts,
       COUNT(*)::NUMERIC / SUM(COUNT(*)) OVER ()       AS share_of_events,
       AVG((refund_amount_usd > 0)::INT)               AS refund_share,
       SUM(refund_amount_usd)                          AS total_refund_usd,
       AVG(preceding_upgrade_flag::INT)                AS preceding_upgrade_share,
       AVG(preceding_downgrade_flag::INT)              AS preceding_downgrade_share,
       AVG(is_reactivation::INT)                       AS reactivation_share,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_since_signup) AS median_days_since_signup
FROM analytics.v_churn_events
GROUP BY reason_code
ORDER BY events DESC;

-- name: churn_reasons_by_plan
SELECT plan_tier,
       COUNT(*) AS events,
       AVG((reason_code = 'features')::INT)   AS features,
       AVG((reason_code = 'support')::INT)    AS support,
       AVG((reason_code = 'budget')::INT)     AS budget,
       AVG((reason_code = 'pricing')::INT)    AS pricing,
       AVG((reason_code = 'competitor')::INT) AS competitor,
       AVG((reason_code = 'unknown')::INT)    AS unknown
FROM analytics.v_churn_events
GROUP BY plan_tier
ORDER BY CASE plan_tier WHEN 'Basic' THEN 1 WHEN 'Pro' THEN 2 ELSE 3 END;

-- name: churn_reason_vs_feedback
-- Consistency check between structured reason and free-text feedback
SELECT reason_code,
       COUNT(*) FILTER (WHERE feedback_text = 'too expensive')          AS too_expensive,
       COUNT(*) FILTER (WHERE feedback_text = 'missing features')       AS missing_features,
       COUNT(*) FILTER (WHERE feedback_text = 'switched to competitor') AS switched_to_competitor,
       COUNT(*) FILTER (WHERE feedback_text IS NULL)                    AS no_feedback
FROM analytics.v_churn_events
GROUP BY reason_code
ORDER BY reason_code;

-- name: churn_events_quarterly
WITH q AS (
    SELECT DATE_TRUNC('quarter', churn_date)::DATE AS quarter,
           COUNT(*)                                AS churn_events,
           COUNT(DISTINCT account_id)              AS accounts,
           AVG(is_reactivation::INT)               AS reactivation_share
    FROM analytics.v_churn_events
    GROUP BY 1
)
SELECT q.*,
       churn_events - LAG(churn_events) OVER (ORDER BY quarter) AS qoq_change,
       SUM(churn_events) OVER (ORDER BY quarter)                AS cumulative_events
FROM q
ORDER BY quarter;

-- name: churned_vs_retained_profile
SELECT churn_flag,
       COUNT(*)                                                           AS accounts,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_usage_count)     AS median_usage_count,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY distinct_features)     AS median_distinct_features,
       AVG(error_rate)                                                    AS mean_error_rate,
       AVG(n_tickets)                                                     AS mean_tickets,
       AVG(any_escalation::INT)                                           AS escalation_share,
       AVG(avg_satisfaction)                                              AS mean_account_csat,
       AVG(seats)                                                         AS mean_seats,
       AVG(n_upgrades)                                                    AS mean_upgrades,
       AVG(n_downgrades)                                                  AS mean_downgrades
FROM analytics.account_features
GROUP BY churn_flag
ORDER BY churn_flag;
