/* =====================================================================================
   02_data_quality.sql  -  post-load validation
   Every "-- name:" query returns a result set exported by src/data/run_sql.py to
   outputs/tables/sql/02_data_quality__<name>.csv
   ===================================================================================== */

-- name: dq_row_counts
SELECT 'accounts' AS table_name, COUNT(*) AS row_count FROM core.accounts
UNION ALL SELECT 'subscriptions',   COUNT(*) FROM core.subscriptions
UNION ALL SELECT 'feature_usage',   COUNT(*) FROM core.feature_usage
UNION ALL SELECT 'support_tickets', COUNT(*) FROM core.support_tickets
UNION ALL SELECT 'churn_events',    COUNT(*) FROM core.churn_events;

-- name: dq_referential_integrity
-- LEFT JOIN anti-joins: rows whose parent key does not exist (expected 0 everywhere)
SELECT 'subscriptions -> accounts' AS relationship, COUNT(*) AS orphan_rows
FROM core.subscriptions s LEFT JOIN core.accounts a ON a.account_id = s.account_id
WHERE a.account_id IS NULL
UNION ALL
SELECT 'feature_usage -> subscriptions', COUNT(*)
FROM core.feature_usage u LEFT JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
WHERE s.subscription_id IS NULL
UNION ALL
SELECT 'support_tickets -> accounts', COUNT(*)
FROM core.support_tickets t LEFT JOIN core.accounts a ON a.account_id = t.account_id
WHERE a.account_id IS NULL
UNION ALL
SELECT 'churn_events -> accounts', COUNT(*)
FROM core.churn_events c LEFT JOIN core.accounts a ON a.account_id = c.account_id
WHERE a.account_id IS NULL
UNION ALL
SELECT 'accounts without any subscription', COUNT(*)
FROM core.accounts a LEFT JOIN core.subscriptions s ON s.account_id = a.account_id
WHERE s.subscription_id IS NULL;

-- name: dq_date_ranges
SELECT 'accounts.signup_date' AS column_name, MIN(signup_date)::TEXT AS min_value, MAX(signup_date)::TEXT AS max_value FROM core.accounts
UNION ALL SELECT 'subscriptions.start_date', MIN(start_date)::TEXT, MAX(start_date)::TEXT FROM core.subscriptions
UNION ALL SELECT 'subscriptions.end_date', MIN(end_date)::TEXT, MAX(end_date)::TEXT FROM core.subscriptions
UNION ALL SELECT 'feature_usage.usage_date', MIN(usage_date)::TEXT, MAX(usage_date)::TEXT FROM core.feature_usage
UNION ALL SELECT 'support_tickets.submitted_at', MIN(submitted_at)::TEXT, MAX(submitted_at)::TEXT FROM core.support_tickets
UNION ALL SELECT 'churn_events.churn_date', MIN(churn_date)::TEXT, MAX(churn_date)::TEXT FROM core.churn_events;

-- name: dq_null_profile
SELECT 'subscriptions.end_date' AS column_name, COUNT(*) FILTER (WHERE end_date IS NULL) AS null_rows, COUNT(*) AS total_rows FROM core.subscriptions
UNION ALL SELECT 'support_tickets.satisfaction_score', COUNT(*) FILTER (WHERE satisfaction_score IS NULL), COUNT(*) FROM core.support_tickets
UNION ALL SELECT 'churn_events.feedback_text', COUNT(*) FILTER (WHERE feedback_text IS NULL), COUNT(*) FROM core.churn_events
UNION ALL SELECT 'accounts.first_churn_date', COUNT(*) FILTER (WHERE first_churn_date IS NULL), COUNT(*) FROM core.accounts;

-- name: dq_business_rule_checks
-- Recomputes each cleaning flag independently in SQL and compares with the stored flag.
WITH checks AS (
    SELECT 'subscriptions: 0-day subscription' AS check_name,
           COUNT(*) FILTER (WHERE end_date = start_date) AS recomputed,
           COUNT(*) FILTER (WHERE dq_zero_duration) AS stored_flag
    FROM core.subscriptions
    UNION ALL
    SELECT 'subscriptions: mrr != seats x list price',
           COUNT(*) FILTER (WHERE mrr_amount <> CASE WHEN is_trial THEN 0
                                                     ELSE seats * CASE plan_tier WHEN 'Basic' THEN 19 WHEN 'Pro' THEN 49 ELSE 199 END END),
           COUNT(*) FILTER (WHERE dq_mrr_pricing_mismatch)
    FROM core.subscriptions
    UNION ALL
    SELECT 'subscriptions: upgrade and downgrade flags both set',
           COUNT(*) FILTER (WHERE upgrade_flag AND downgrade_flag),
           COUNT(*) FILTER (WHERE dq_upgrade_and_downgrade)
    FROM core.subscriptions
    UNION ALL
    SELECT 'feature_usage: usage before subscription start',
           COUNT(*) FILTER (WHERE u.usage_date < s.start_date),
           COUNT(*) FILTER (WHERE u.dq_before_subscription_start)
    FROM core.feature_usage u JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
    UNION ALL
    SELECT 'feature_usage: usage after subscription end',
           COUNT(*) FILTER (WHERE u.usage_date > s.end_date),
           COUNT(*) FILTER (WHERE u.dq_after_subscription_end)
    FROM core.feature_usage u JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
    UNION ALL
    SELECT 'feature_usage: usage before account signup',
           COUNT(*) FILTER (WHERE u.usage_date < a.signup_date),
           COUNT(*) FILTER (WHERE u.dq_before_account_signup)
    FROM core.feature_usage u
    JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
    JOIN core.accounts a      ON a.account_id = s.account_id
    UNION ALL
    SELECT 'feature_usage: usage_id reused by different records',
           (SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM core.feature_usage GROUP BY usage_id HAVING COUNT(*) > 1) d),
           COUNT(*) FILTER (WHERE dq_duplicate_usage_id)
    FROM core.feature_usage
    UNION ALL
    SELECT 'support_tickets: first response slower than resolution',
           COUNT(*) FILTER (WHERE first_response_time_minutes > resolution_time_hours * 60),
           COUNT(*) FILTER (WHERE dq_first_response_after_resolution)
    FROM core.support_tickets
    UNION ALL
    SELECT 'support_tickets: submitted before account signup',
           COUNT(*) FILTER (WHERE t.submitted_at < a.signup_date),
           COUNT(*) FILTER (WHERE t.dq_before_account_signup)
    FROM core.support_tickets t JOIN core.accounts a ON a.account_id = t.account_id
    UNION ALL
    SELECT 'churn_events: repeated account + churn_date',
           (SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) AS n FROM core.churn_events GROUP BY account_id, churn_date HAVING COUNT(*) > 1) d),
           COUNT(*) FILTER (WHERE dq_duplicate_account_date)
    FROM core.churn_events
    UNION ALL
    SELECT 'accounts: churn_flag disagrees with churn_events',
           COUNT(*) FILTER (WHERE a.churn_flag <> EXISTS (SELECT 1 FROM core.churn_events c
                                                          WHERE c.account_id = a.account_id AND NOT c.dq_duplicate_account_date)),
           COUNT(*) FILTER (WHERE a.dq_churn_flag_conflict)
    FROM core.accounts a
)
SELECT check_name, recomputed, stored_flag, recomputed = stored_flag AS flag_matches
FROM checks;

-- name: dq_churn_status_crosstab
-- The two churn sources disagree; this is why churn_flag (status) and churn_events (episodes) are used separately.
SELECT churn_flag,
       COUNT(*) FILTER (WHERE has_churn_event)     AS with_churn_event,
       COUNT(*) FILTER (WHERE NOT has_churn_event) AS without_churn_event,
       COUNT(*)                                    AS accounts
FROM core.accounts
GROUP BY churn_flag
ORDER BY churn_flag;
