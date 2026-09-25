/* =====================================================================================
   04_funnel_analysis.sql

   No onboarding/activation events exist and every account has a paid subscription, so the
   funnels use states that do exist (each stage requires all previous stages):
     trial     : Signed up -> Started a trial -> Converted to paid after trial -> Retained
     expansion : Signed up -> Paying -> Upgraded -> Retained
   "Retained" = accounts.churn_flag = FALSE.
   ===================================================================================== */

CREATE OR REPLACE VIEW analytics.v_account_funnel AS
SELECT account_id, plan_tier, referral_source, industry, signup_quarter, signup_month,
       TRUE                                                                   AS stage_signed_up,
       has_trial_subscription                                                 AS stage_trial_started,
       has_trial_subscription AND COALESCE(trial_converted, FALSE)            AS stage_trial_converted,
       has_trial_subscription AND COALESCE(trial_converted, FALSE) AND NOT churn_flag AS stage_trial_retained,
       n_paid_subscriptions > 0                                               AS stage_paying,
       n_paid_subscriptions > 0 AND any_upgrade                               AS stage_upgraded,
       n_paid_subscriptions > 0 AND any_upgrade AND NOT churn_flag            AS stage_expansion_retained
FROM analytics.account_features;

CREATE OR REPLACE VIEW analytics.v_funnel_stage_counts AS
WITH dims AS (
    SELECT f.*, d.dimension, d.segment
    FROM analytics.v_account_funnel f
    CROSS JOIN LATERAL (VALUES ('overall', 'All'),
                               ('plan_tier', f.plan_tier),
                               ('referral_source', f.referral_source),
                               ('industry', f.industry),
                               ('signup_quarter', f.signup_quarter)) AS d(dimension, segment)
),
stage_counts AS (
    SELECT dims.dimension, dims.segment, v.funnel, v.stage_order, v.stage,
           COUNT(*) FILTER (WHERE v.reached) AS accounts
    FROM dims
    CROSS JOIN LATERAL (VALUES
        ('trial',     1, '1. Signed up',                     dims.stage_signed_up),
        ('trial',     2, '2. Started a trial',               dims.stage_trial_started),
        ('trial',     3, '3. Converted to paid after trial', dims.stage_trial_converted),
        ('trial',     4, '4. Retained (not churned)',        dims.stage_trial_retained),
        ('expansion', 1, '1. Signed up',                     dims.stage_signed_up),
        ('expansion', 2, '2. Paying',                        dims.stage_paying),
        ('expansion', 3, '3. Upgraded',                      dims.stage_upgraded),
        ('expansion', 4, '4. Retained (not churned)',        dims.stage_expansion_retained)
    ) AS v(funnel, stage_order, stage, reached)
    GROUP BY dims.dimension, dims.segment, v.funnel, v.stage_order, v.stage
)
SELECT dimension, segment, funnel, stage_order, stage, accounts,
       accounts::NUMERIC / FIRST_VALUE(accounts) OVER w          AS conversion_from_signup,
       accounts::NUMERIC / NULLIF(LAG(accounts) OVER w, 0)       AS step_conversion,
       1 - accounts::NUMERIC / NULLIF(LAG(accounts) OVER w, 0)   AS step_drop_off
FROM stage_counts
WINDOW w AS (PARTITION BY dimension, segment, funnel ORDER BY stage_order);

-- name: funnel_overall
SELECT funnel, stage_order, stage, accounts, conversion_from_signup, step_conversion, step_drop_off
FROM analytics.v_funnel_stage_counts
WHERE dimension = 'overall'
ORDER BY funnel DESC, stage_order;

-- name: funnel_bottleneck
-- Largest step-to-step drop-off within each funnel
SELECT funnel, stage AS bottleneck_stage, accounts, step_conversion, step_drop_off
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY funnel ORDER BY step_drop_off DESC) AS rn
    FROM analytics.v_funnel_stage_counts
    WHERE dimension = 'overall' AND step_drop_off IS NOT NULL
) ranked
WHERE rn = 1;

-- name: funnel_by_segment
SELECT dimension, segment, funnel, stage_order, stage, accounts, conversion_from_signup, step_conversion, step_drop_off
FROM analytics.v_funnel_stage_counts
WHERE dimension <> 'overall'
ORDER BY funnel DESC, dimension, segment, stage_order;

-- name: trial_conversion_ranking
-- Trial-to-paid step conversion ranked within each dimension, with gap to the dimension average
WITH conv AS (
    SELECT dimension, segment,
           LAG(accounts) OVER (PARTITION BY dimension, segment ORDER BY stage_order) AS trial_accounts,
           accounts AS converted_accounts,
           stage_order
    FROM analytics.v_funnel_stage_counts
    WHERE funnel = 'trial' AND stage_order IN (2, 3) AND dimension <> 'overall'
)
SELECT dimension, segment, trial_accounts, converted_accounts,
       converted_accounts::NUMERIC / trial_accounts                                      AS trial_to_paid_rate,
       converted_accounts::NUMERIC / trial_accounts
         - SUM(converted_accounts) OVER (PARTITION BY dimension)::NUMERIC
           / SUM(trial_accounts) OVER (PARTITION BY dimension)                           AS gap_vs_dimension_rate,
       RANK() OVER (PARTITION BY dimension ORDER BY converted_accounts::NUMERIC / trial_accounts DESC) AS rank_in_dimension
FROM conv
WHERE stage_order = 3
ORDER BY dimension, rank_in_dimension;

-- name: funnel_retention_step_by_channel
-- Expansion funnel: upgraded -> retained, by acquisition channel
SELECT segment AS referral_source,
       MAX(accounts) FILTER (WHERE stage_order = 3) AS upgraded_accounts,
       MAX(accounts) FILTER (WHERE stage_order = 4) AS retained_accounts,
       MAX(step_conversion) FILTER (WHERE stage_order = 4) AS upgraded_to_retained_rate
FROM analytics.v_funnel_stage_counts
WHERE funnel = 'expansion' AND dimension = 'referral_source'
GROUP BY segment
ORDER BY upgraded_to_retained_rate;
