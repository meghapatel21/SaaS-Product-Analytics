# Data Dictionary

**Source:** [RavenStack SaaS Subscription & Churn Analytics dataset](https://www.kaggle.com/datasets/rivalytics/saas-subscription-and-churn-analytics-dataset) by River @ Rivalytics (synthetic, MIT-like licence). Raw files are in `dataset/raw/`.
**Snapshot date:** 2024-12-31, the latest date in any table. Data covers 2023-01-01 to 2024-12-31.

| Table | File | Rows | Columns (raw → processed) | Primary key | Grain |
|---|---|---:|---|---|---|
| accounts | `ravenstack_accounts.csv` | 500 | 10 → 17 | `account_id` | one customer account |
| subscriptions | `ravenstack_subscriptions.csv` | 5,000 | 14 → 24 | `subscription_id` | one subscription / billing line item |
| feature_usage | `ravenstack_feature_usage.csv` | 25,000 | 8 → 17 | `usage_row_id` (surrogate) | one usage record of one feature on one day |
| support_tickets | `ravenstack_support_tickets.csv` | 2,000 | 9 → 14 | `ticket_id` | one support ticket |
| churn_events | `ravenstack_churn_events.csv` | 600 | 9 → 11 | `churn_event_id` | one churn episode |

**Relationships** (no orphan keys in any of them): `accounts 1–N subscriptions 1–N feature_usage`, `accounts 1–N support_tickets`, `accounts 1–N churn_events`.
**No individual-user table exists.** "Users" in the project brief map to **accounts**. `seats` is the number of licensed users.

Nullable = whether NULLs occur in the data. Key: PK = primary key, FK = foreign key.

## accounts

| Column | Type | Meaning | Example | Nullable | Key | Analytical purpose |
|---|---|---|---|---|---|---|
| account_id | varchar | Unique customer account | `A-2e4581` | No | PK | Join key; unit of analysis |
| account_name | text | Fictional company name | `Company_0` | No | | Labels only |
| industry | text | Vertical: DevTools, FinTech, Cybersecurity, HealthTech, EdTech | `EdTech` | No | | Customer segment |
| country | char(2) | Country code: US, UK, IN, AU, DE, CA, FR | `US` | No | | Geographic segment |
| signup_date | date | Account creation date (2023-01-02 → 2024-12-31) | `2024-10-16` | No | | Signup cohorts, tenure |
| referral_source | text | Acquisition channel: organic, ads, event, partner, other | `partner` | No | | Channel analysis |
| plan_tier | text | Plan recorded on the account (README: "initial plan") | `Basic` | No | | Plan segment. **Matches the first subscription's plan for only 33% of accounts** |
| seats | integer | Licensed user count on the account (1–163) | `9` | No | | Account size |
| is_trial | boolean | Currently trialling (README) | `False` | No | | Descriptive; 97 TRUE |
| churn_flag | boolean | Churned at any point (README) | `False` | No | | **Primary account churn label** (110 TRUE) |
| *signup_month* | date | Derived: first day of signup month | `2024-10-01` | No | | Cohort key |
| *tenure_days* | integer | Derived: snapshot − signup_date | `76` | No | | Account age |
| *n_churn_events* | integer | Derived: churn events for the account (repeated same-day event excluded) | `2` | No | | Churn episodes |
| *first_churn_date* / *last_churn_date* | date | Derived: first / last churn event date | `2024-06-25` | Yes (148 have none) | | Time to first churn |
| *has_churn_event* | boolean | Derived: n_churn_events > 0 | `True` | No | | Event-based churn |
| *dq_churn_flag_conflict* | boolean | Derived: churn_flag ≠ has_churn_event | `True` | No | | Data-quality flag (312 TRUE) |

## subscriptions

| Column | Type | Meaning | Example | Nullable | Key | Analytical purpose |
|---|---|---|---|---|---|---|
| subscription_id | varchar | Unique subscription | `S-8cec59` | No | PK | Join key |
| account_id | varchar | Owning account | `A-3c1a3f` | No | FK → accounts | Account roll-ups |
| start_date | date | Subscription start (2023-01-09 → 2024-12-31) | `2023-12-23` | No | | Retention cohorts, MRR timing |
| end_date | date | Subscription end; NULL = still active | `2024-04-12` | Yes (4,514) | | Churn timing, active status |
| plan_tier | text | Plan at time of billing | `Enterprise` | No | | Plan analysis, pricing |
| seats | integer | Licensed seats (1–189) | `14` | No | | Revenue per seat |
| mrr_amount | integer (USD) | Monthly recurring revenue. Always seats × $19 / $49 / $199, and 0 for trials | `2786` | No | | MRR, ARPA |
| arr_amount | integer (USD) | Annual revenue, always 12 × MRR | `33432` | No | | ARR |
| is_trial | boolean | Trial subscription (MRR = 0) | `False` | No | | Trial funnel |
| upgrade_flag | boolean | Plan upgraded mid-cycle | `False` | No | | Expansion funnel. **Not tied to tier changes between subscriptions** |
| downgrade_flag | boolean | Plan downgraded mid-cycle | `False` | No | | Contraction |
| churn_flag | boolean | TRUE exactly when end_date is set | `True` | No | | Subscription churn |
| billing_frequency | text | monthly / annual | `monthly` | No | | Billing segment |
| auto_renew_flag | boolean | Auto-renew enabled | `True` | No | | Renewal segment |
| *is_paid* | boolean | Derived: NOT is_trial | `True` | No | | Paid subscriptions |
| *start_month* | date | Derived: first day of start month | `2023-12-01` | No | | Cohort key |
| *is_active_at_snapshot* | boolean | Derived: end_date IS NULL | `False` | No | | Snapshot MRR |
| *duration_days* | integer | Derived: (end_date or snapshot) − start_date | `111` | No | | Survival analysis |
| *dq_end_before_start*, *dq_zero_duration*, *dq_start_before_signup*, *dq_churn_flag_end_date_mismatch*, *dq_mrr_pricing_mismatch*, *dq_upgrade_and_downgrade* | boolean | Data-quality flags (see DATA_QUALITY_REPORT) | `False` | No | | Include/exclude decisions |

## feature_usage

| Column | Type | Meaning | Example | Nullable | Key | Analytical purpose |
|---|---|---|---|---|---|---|
| *usage_row_id* | integer | Derived surrogate key (raw file order) | `1` | No | PK | Needed because usage_id repeats |
| usage_id | varchar | Source usage ID. **21 values are reused by different records** | `U-1c6c24` | No | | Traceability only |
| subscription_id | varchar | Subscription the usage belongs to | `S-0fcf7d` | No | FK → subscriptions | Links usage to account and plan |
| usage_date | date | Date of usage (2023-01-01 → 2024-12-31) | `2023-07-27` | No | | Calendar usage trend (with caveats) |
| feature_name | text | One of 40 anonymised features (`feature_1` … `feature_40`) | `feature_20` | No | | Feature adoption |
| usage_count | integer | Number of uses in the record (0–26) | `9` | No | | Usage intensity |
| usage_duration_secs | integer | Time spent in seconds (0–12,696) | `5004` | No | | Engagement depth |
| error_count | integer | Errors logged (0–8) | `0` | No | | Friction |
| is_beta_feature | boolean | Usage was of a beta release (varies by row within a feature) | `False` | No | | Beta vs GA quality |
| *dq_duplicate_usage_id*, *dq_same_sub_date_feature*, *dq_zero_usage* | boolean | Data-quality flags | `False` | No | | |
| *dq_before_subscription_start*, *dq_after_subscription_end*, *dq_before_account_signup* | boolean | Temporal misalignment flags | `True` | No | | Explains why usage is not lifecycle-aligned |
| *is_in_subscription_window* | boolean | Derived: usage within its subscription dates | `False` | No | | Sensitivity checks |
| *usage_month* | date | Derived: first day of usage month | `2023-07-01` | No | | Monthly trend |

## support_tickets

| Column | Type | Meaning | Example | Nullable | Key | Analytical purpose |
|---|---|---|---|---|---|---|
| ticket_id | varchar | Unique ticket | `T-0024de` | No | PK | |
| account_id | varchar | Account raising the ticket | `A-712f1c` | No | FK → accounts | Support load per account |
| submitted_at | timestamp | Time opened (date precision in source) | `2023-07-27 00:00:00` | No | | Monthly volume |
| closed_at | timestamp | Time resolved | `2023-07-28 03:00:00` | No | | |
| resolution_time_hours | numeric | closed_at − submitted_at in hours (1–72; verified equal) | `27.0` | No | | Resolution KPI |
| priority | text | low / medium / high / urgent | `high` | No | | SLA analysis |
| first_response_time_minutes | integer | Minutes to first response (1–180) | `74` | No | | Responsiveness KPI |
| satisfaction_score | smallint | CSAT; observed values are only 3–5. NULL = no response | `4` | Yes (825) | | CSAT KPI |
| escalation_flag | boolean | Ticket escalated | `False` | No | | Escalation rate, churn association |
| *has_satisfaction_response* | boolean | Derived: satisfaction_score IS NOT NULL | `False` | No | | CSAT response rate |
| *submitted_month* | date | Derived | `2023-07-01` | No | | |
| *dq_first_response_after_resolution*, *dq_satisfaction_out_of_range*, *dq_before_account_signup* | boolean | Data-quality flags | `False` | No | | |

## churn_events

| Column | Type | Meaning | Example | Nullable | Key | Analytical purpose |
|---|---|---|---|---|---|---|
| churn_event_id | varchar | Unique churn episode | `C-816288` | No | PK | |
| account_id | varchar | Churning account | `A-c37cab` | No | FK → accounts | |
| churn_date | date | Date the account left (2023-01-25 → 2024-12-31) | `2024-10-27` | No | | Churn timing |
| reason_code | text | pricing, support, features, budget, competitor, unknown | `pricing` | No | | Churn reasons |
| refund_amount_usd | numeric | Refund / credit issued (0–392.92; 76% are 0) | `4.03` | No | | Refund cost |
| preceding_upgrade_flag | boolean | Upgrade within the prior 90 days | `False` | No | | Behaviour before churn |
| preceding_downgrade_flag | boolean | Downgrade within the prior 90 days | `False` | No | | Behaviour before churn |
| is_reactivation | boolean | Account had churned before (61 TRUE) | `False` | No | | Reactivation analysis |
| feedback_text | text | too expensive / missing features / switched to competitor | `switched to competitor` | Yes (148) | | Qualitative reason. **Does not match reason_code** |
| *dq_duplicate_account_date* | boolean | Derived: second event for the same account and date | `False` | No | | Excluded from counts |
| *churn_month* | date | Derived | `2024-10-01` | No | | Monthly trend |

## Analytical mart: `analytics.account_features` / `dataset/processed/account_features.csv`

One row per account (500), built in `src/analysis/marts.py` and `sql/01_schema.sql`. Behavioural and support fields are **lifetime aggregates**.

| Column(s) | Meaning |
|---|---|
| n_subscriptions, n_paid_subscriptions, n_trial_subscriptions, n_ended_subscriptions | Subscription counts |
| has_trial_subscription, trial_converted | Account had a trial; had a paid subscription starting on/after its first trial start |
| n_upgrades, n_downgrades, any_upgrade, any_downgrade, highest_plan_tier | Expansion/contraction history |
| n_active_subscriptions, mrr_at_snapshot, paid_seats_at_snapshot | State on 2024-12-31 |
| usage_events, total_usage_count, distinct_features, total_duration_hours, avg_minutes_per_event, error_rate, beta_event_share | Lifetime usage behaviour |
| n_tickets, n_escalations, any_escalation, n_high_urgent_tickets, avg_resolution_hours, avg_first_response_minutes, csat_responses, avg_satisfaction | Lifetime support experience |
| signup_quarter, tenure_bucket, ticket_bucket, breadth_quartile, usage_quartile | Banding for segmentation (P25/P50/P75 thresholds) |
| engagement_segment, high_friction | Rule-based segments (rules in `docs/ANALYSIS_PLAN.md`) |

## Potential targets and fields not present

* **Targets:** `accounts.churn_flag` (account churn), `subscriptions.churn_flag` / `end_date` (subscription churn and survival), `churn_events` (churn episodes).
* **Not present:** user IDs, sessions or login events, onboarding or activation events, marketing spend, experiment/variant/exposure fields, price changes, invoices or payments.
