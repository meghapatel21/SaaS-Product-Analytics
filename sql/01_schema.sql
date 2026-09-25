/* =====================================================================================
   01_schema.sql  -  RavenStack product analytics data model (PostgreSQL 14+)

   Run via:  python -m src.data.load_postgres   (creates the database, runs this file,
             bulk-loads the CSV files in dataset/processed with COPY)

   Layers
     core.*       cleaned tables (1:1 with dataset/processed), keys + constraints
     analytics.*  reusable analytical views; the Tableau data sources live here

   Relationships (all verified complete in 02_data_quality.sql)
     accounts 1-N subscriptions 1-N feature_usage
     accounts 1-N support_tickets
     accounts 1-N churn_events
   ===================================================================================== */

DROP SCHEMA IF EXISTS analytics CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA analytics;

-- ---------------------------------------------------------------------------------------
-- core.accounts : one row per customer account
-- ---------------------------------------------------------------------------------------
CREATE TABLE core.accounts (
    account_id              VARCHAR(16) PRIMARY KEY,
    account_name            TEXT        NOT NULL,
    industry                TEXT        NOT NULL CHECK (industry IN ('DevTools', 'FinTech', 'Cybersecurity', 'HealthTech', 'EdTech')),
    country                 CHAR(2)     NOT NULL,
    signup_date             DATE        NOT NULL,
    referral_source         TEXT        NOT NULL CHECK (referral_source IN ('organic', 'ads', 'event', 'partner', 'other')),
    plan_tier               TEXT        NOT NULL CHECK (plan_tier IN ('Basic', 'Pro', 'Enterprise')),
    seats                   INTEGER     NOT NULL CHECK (seats > 0),
    is_trial                BOOLEAN     NOT NULL,
    churn_flag              BOOLEAN     NOT NULL,
    signup_month            DATE        NOT NULL,
    tenure_days             INTEGER     NOT NULL CHECK (tenure_days >= 0),
    n_churn_events          INTEGER     NOT NULL CHECK (n_churn_events >= 0),
    first_churn_date        DATE,
    last_churn_date         DATE,
    has_churn_event         BOOLEAN     NOT NULL,
    dq_churn_flag_conflict  BOOLEAN     NOT NULL,
    CHECK (first_churn_date IS NULL OR first_churn_date >= signup_date)
);

-- ---------------------------------------------------------------------------------------
-- core.subscriptions : billing line items; an account can hold several at once
-- ---------------------------------------------------------------------------------------
CREATE TABLE core.subscriptions (
    subscription_id                  VARCHAR(16) PRIMARY KEY,
    account_id                       VARCHAR(16) NOT NULL REFERENCES core.accounts (account_id),
    start_date                       DATE        NOT NULL,
    end_date                         DATE,
    plan_tier                        TEXT        NOT NULL CHECK (plan_tier IN ('Basic', 'Pro', 'Enterprise')),
    seats                            INTEGER     NOT NULL CHECK (seats > 0),
    mrr_amount                       INTEGER     NOT NULL CHECK (mrr_amount >= 0),
    arr_amount                       INTEGER     NOT NULL,
    is_trial                         BOOLEAN     NOT NULL,
    upgrade_flag                     BOOLEAN     NOT NULL,
    downgrade_flag                   BOOLEAN     NOT NULL,
    churn_flag                       BOOLEAN     NOT NULL,
    billing_frequency                TEXT        NOT NULL CHECK (billing_frequency IN ('monthly', 'annual')),
    auto_renew_flag                  BOOLEAN     NOT NULL,
    dq_end_before_start              BOOLEAN     NOT NULL,
    dq_zero_duration                 BOOLEAN     NOT NULL,
    dq_start_before_signup           BOOLEAN     NOT NULL,
    dq_churn_flag_end_date_mismatch  BOOLEAN     NOT NULL,
    dq_mrr_pricing_mismatch          BOOLEAN     NOT NULL,
    dq_upgrade_and_downgrade         BOOLEAN     NOT NULL,
    is_paid                          BOOLEAN     NOT NULL,
    start_month                      DATE        NOT NULL,
    is_active_at_snapshot            BOOLEAN     NOT NULL,
    duration_days                    INTEGER     NOT NULL CHECK (duration_days >= 0),
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK (arr_amount = 12 * mrr_amount),
    CHECK (is_paid = NOT is_trial),
    CHECK (churn_flag = (end_date IS NOT NULL))
);

-- ---------------------------------------------------------------------------------------
-- core.feature_usage : feature usage records. usage_id is NOT unique in the source
-- (21 IDs reused by different records) so a surrogate key is used.
-- ---------------------------------------------------------------------------------------
CREATE TABLE core.feature_usage (
    usage_row_id                  INTEGER     PRIMARY KEY,
    usage_id                      VARCHAR(16) NOT NULL,
    subscription_id               VARCHAR(16) NOT NULL REFERENCES core.subscriptions (subscription_id),
    usage_date                    DATE        NOT NULL,
    feature_name                  TEXT        NOT NULL,
    usage_count                   INTEGER     NOT NULL CHECK (usage_count >= 0),
    usage_duration_secs           INTEGER     NOT NULL CHECK (usage_duration_secs >= 0),
    error_count                   INTEGER     NOT NULL CHECK (error_count >= 0),
    is_beta_feature               BOOLEAN     NOT NULL,
    dq_duplicate_usage_id         BOOLEAN     NOT NULL,
    dq_same_sub_date_feature      BOOLEAN     NOT NULL,
    dq_zero_usage                 BOOLEAN     NOT NULL,
    dq_before_subscription_start  BOOLEAN     NOT NULL,
    dq_after_subscription_end     BOOLEAN     NOT NULL,
    dq_before_account_signup      BOOLEAN     NOT NULL,
    is_in_subscription_window     BOOLEAN     NOT NULL,
    usage_month                   DATE        NOT NULL
);

-- ---------------------------------------------------------------------------------------
-- core.support_tickets
-- ---------------------------------------------------------------------------------------
CREATE TABLE core.support_tickets (
    ticket_id                           VARCHAR(16)  PRIMARY KEY,
    account_id                          VARCHAR(16)  NOT NULL REFERENCES core.accounts (account_id),
    submitted_at                        TIMESTAMP    NOT NULL,
    closed_at                           TIMESTAMP    NOT NULL,
    resolution_time_hours               NUMERIC(8,2) NOT NULL CHECK (resolution_time_hours > 0),
    priority                            TEXT         NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    first_response_time_minutes         INTEGER      NOT NULL CHECK (first_response_time_minutes > 0),
    satisfaction_score                  SMALLINT     CHECK (satisfaction_score BETWEEN 1 AND 5),
    escalation_flag                     BOOLEAN      NOT NULL,
    dq_first_response_after_resolution  BOOLEAN      NOT NULL,
    dq_satisfaction_out_of_range        BOOLEAN      NOT NULL,
    has_satisfaction_response           BOOLEAN      NOT NULL,
    dq_before_account_signup            BOOLEAN      NOT NULL,
    submitted_month                     DATE         NOT NULL,
    CHECK (closed_at >= submitted_at)
);

-- ---------------------------------------------------------------------------------------
-- core.churn_events : churn episodes (an account can churn, reactivate and churn again)
-- ---------------------------------------------------------------------------------------
CREATE TABLE core.churn_events (
    churn_event_id             VARCHAR(16)   PRIMARY KEY,
    account_id                 VARCHAR(16)   NOT NULL REFERENCES core.accounts (account_id),
    churn_date                 DATE          NOT NULL,
    reason_code                TEXT          NOT NULL CHECK (reason_code IN ('pricing', 'support', 'features', 'budget', 'competitor', 'unknown')),
    refund_amount_usd          NUMERIC(10,2) NOT NULL CHECK (refund_amount_usd >= 0),
    preceding_upgrade_flag     BOOLEAN       NOT NULL,
    preceding_downgrade_flag   BOOLEAN       NOT NULL,
    is_reactivation            BOOLEAN       NOT NULL,
    feedback_text              TEXT,
    dq_duplicate_account_date  BOOLEAN       NOT NULL,
    churn_month                DATE          NOT NULL
);

-- ---------------------------------------------------------------------------------------
-- Indexes: foreign keys and the date columns used for windows / cohorts
-- ---------------------------------------------------------------------------------------
CREATE INDEX ix_subscriptions_account      ON core.subscriptions (account_id);
CREATE INDEX ix_subscriptions_dates        ON core.subscriptions (start_date, end_date);
CREATE INDEX ix_feature_usage_subscription ON core.feature_usage (subscription_id);
CREATE INDEX ix_feature_usage_feature_date ON core.feature_usage (feature_name, usage_date);
CREATE INDEX ix_feature_usage_usage_id     ON core.feature_usage (usage_id);
CREATE INDEX ix_support_tickets_account    ON core.support_tickets (account_id);
CREATE INDEX ix_churn_events_account_date  ON core.churn_events (account_id, churn_date);

-- =======================================================================================
-- Analytics layer (views are lazy, so they can be created before data is loaded)
-- =======================================================================================

CREATE VIEW analytics.params AS
SELECT DATE '2024-12-31' AS snapshot_date;   -- latest date observed in any table

/* analytics.account_features : one row per account. SQL twin of src/analysis/marts.py.
   Behaviour/support measures are lifetime aggregates (usage & ticket dates are not
   aligned with account lifecycles - see docs/DATA_QUALITY_REPORT.md). */
CREATE VIEW analytics.account_features AS
WITH sub AS (
    SELECT account_id,
           COUNT(*)                                                           AS n_subscriptions,
           COUNT(*) FILTER (WHERE NOT is_trial)                               AS n_paid_subscriptions,
           COUNT(*) FILTER (WHERE is_trial)                                   AS n_trial_subscriptions,
           COUNT(*) FILTER (WHERE end_date IS NOT NULL)                       AS n_ended_subscriptions,
           COUNT(*) FILTER (WHERE upgrade_flag)                               AS n_upgrades,
           COUNT(*) FILTER (WHERE downgrade_flag)                             AS n_downgrades,
           COUNT(*) FILTER (WHERE end_date IS NULL)                           AS n_active_subscriptions,
           COALESCE(SUM(mrr_amount) FILTER (WHERE end_date IS NULL), 0)       AS mrr_at_snapshot,
           COALESCE(SUM(seats) FILTER (WHERE end_date IS NULL AND NOT is_trial), 0) AS paid_seats_at_snapshot,
           AVG((billing_frequency = 'annual')::INT)                           AS annual_share,
           MIN(start_date) FILTER (WHERE is_trial)                            AS first_trial_start,
           MAX(CASE plan_tier WHEN 'Basic' THEN 1 WHEN 'Pro' THEN 2 ELSE 3 END) AS highest_plan_rank
    FROM core.subscriptions
    GROUP BY account_id
),
trial AS (
    SELECT s.account_id,
           BOOL_OR(NOT s.is_trial AND s.start_date >= sub.first_trial_start) AS trial_converted
    FROM core.subscriptions s
    JOIN sub ON sub.account_id = s.account_id
    WHERE sub.first_trial_start IS NOT NULL
    GROUP BY s.account_id
),
usage AS (
    SELECT s.account_id,
           COUNT(*)                                                   AS usage_events,
           SUM(u.usage_count)                                         AS total_usage_count,
           COUNT(DISTINCT u.feature_name)                             AS distinct_features,
           SUM(u.usage_duration_secs) / 3600.0                        AS total_duration_hours,
           SUM(u.error_count)::FLOAT8 / NULLIF(SUM(u.usage_count), 0) AS error_rate,
           AVG(u.is_beta_feature::INT)                                AS beta_event_share
    FROM core.feature_usage u
    JOIN core.subscriptions s ON s.subscription_id = u.subscription_id
    GROUP BY s.account_id
),
tickets AS (
    SELECT account_id,
           COUNT(*)                                AS n_tickets,
           COUNT(*) FILTER (WHERE escalation_flag) AS n_escalations,
           AVG(resolution_time_hours)              AS avg_resolution_hours,
           AVG(satisfaction_score)                 AS avg_satisfaction
    FROM core.support_tickets
    GROUP BY account_id
),
base AS (
    SELECT a.account_id, a.account_name, a.industry, a.country, a.referral_source, a.plan_tier, a.seats,
           a.is_trial, a.churn_flag, a.signup_date, a.signup_month,
           TO_CHAR(a.signup_date, 'YYYY"Q"Q')                            AS signup_quarter,
           a.tenure_days,
           CASE WHEN a.tenure_days <= 180 THEN '0-6 months'
                WHEN a.tenure_days <= 365 THEN '6-12 months'
                WHEN a.tenure_days <= 540 THEN '12-18 months'
                ELSE '18-24 months' END                                  AS tenure_bucket,
           a.n_churn_events, a.has_churn_event, a.first_churn_date,
           sub.n_subscriptions, sub.n_paid_subscriptions, sub.n_trial_subscriptions, sub.n_ended_subscriptions,
           sub.n_upgrades, sub.n_downgrades, sub.n_active_subscriptions, sub.mrr_at_snapshot,
           sub.paid_seats_at_snapshot, sub.annual_share,
           sub.n_trial_subscriptions > 0                                 AS has_trial_subscription,
           trial.trial_converted,
           sub.n_upgrades > 0                                            AS any_upgrade,
           sub.n_downgrades > 0                                          AS any_downgrade,
           (ARRAY['Basic', 'Pro', 'Enterprise'])[sub.highest_plan_rank]  AS highest_plan_tier,
           u.usage_events, u.total_usage_count, u.distinct_features, u.total_duration_hours,
           u.error_rate, u.beta_event_share,
           COALESCE(t.n_tickets, 0)                                      AS n_tickets,
           COALESCE(t.n_escalations, 0)                                  AS n_escalations,
           COALESCE(t.n_escalations, 0) > 0                              AS any_escalation,
           t.avg_resolution_hours, t.avg_satisfaction
    FROM core.accounts a
    INNER JOIN sub      ON sub.account_id   = a.account_id   -- every account has >= 1 subscription (02_data_quality)
    LEFT JOIN trial     ON trial.account_id = a.account_id   -- only accounts that trialled
    LEFT JOIN usage u   ON u.account_id     = a.account_id
    LEFT JOIN tickets t ON t.account_id     = a.account_id   -- 8 accounts have no tickets
),
th AS (
    SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p25,
           PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p50,
           PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY total_usage_count) AS usage_p75,
           PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY distinct_features) AS breadth_p25,
           PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY distinct_features) AS breadth_p50,
           PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY distinct_features) AS breadth_p75,
           PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY error_rate)        AS error_rate_p75
    FROM base
)
SELECT b.*,
       CASE WHEN b.n_tickets = 0 THEN '0'
            WHEN b.n_tickets <= 2 THEN '1-2'
            WHEN b.n_tickets <= 4 THEN '3-4'
            WHEN b.n_tickets <= 6 THEN '5-6'
            ELSE '7+' END                                                AS ticket_bucket,
       CASE WHEN b.distinct_features < th.breadth_p25 THEN 'Q1 (lowest)'
            WHEN b.distinct_features < th.breadth_p50 THEN 'Q2'
            WHEN b.distinct_features < th.breadth_p75 THEN 'Q3'
            ELSE 'Q4 (highest)' END                                      AS breadth_quartile,
       CASE WHEN b.total_usage_count < th.usage_p25 THEN 'Q1 (lowest)'
            WHEN b.total_usage_count < th.usage_p50 THEN 'Q2'
            WHEN b.total_usage_count < th.usage_p75 THEN 'Q3'
            ELSE 'Q4 (highest)' END                                      AS usage_quartile,
       CASE WHEN b.total_usage_count >= th.usage_p75 AND b.distinct_features >= th.breadth_p75 THEN 'Power Accounts'
            WHEN b.total_usage_count >= th.usage_p50 THEN 'Engaged Accounts'
            WHEN b.total_usage_count >= th.usage_p25 THEN 'Casual Accounts'
            ELSE 'Low-Engagement Accounts' END                           AS engagement_segment,
       CASE WHEN b.total_usage_count >= th.usage_p75 AND b.distinct_features >= th.breadth_p75 THEN 1
            WHEN b.total_usage_count >= th.usage_p50 THEN 2
            WHEN b.total_usage_count >= th.usage_p25 THEN 3
            ELSE 4 END                                                   AS engagement_segment_order,
       (b.error_rate >= th.error_rate_p75 OR b.n_escalations > 0)       AS high_friction
FROM base b
CROSS JOIN th;
