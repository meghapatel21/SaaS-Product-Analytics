# Dataset Assessment & Implementation Plan

Written after inspecting the raw files and **before** any analysis was designed (Phase 1 of the project brief). Detail is in [DATA_DICTIONARY.md](DATA_DICTIONARY.md) and [DATA_QUALITY_REPORT.md](DATA_QUALITY_REPORT.md).

## 1. Files found

`dataset/raw/`, from the [RavenStack SaaS Subscription & Churn Analytics dataset](https://www.kaggle.com/datasets/rivalytics/saas-subscription-and-churn-analytics-dataset) (River @ Rivalytics, synthetic):
`ravenstack_accounts.csv`, `ravenstack_subscriptions.csv`, `ravenstack_feature_usage.csv`, `ravenstack_support_tickets.csv`, `ravenstack_churn_events.csv`, and the source `README.md`.

## 2. Tables and row counts

| Table | Rows | Columns | Key |
|---|---:|---:|---|
| accounts | 500 | 10 | `account_id` |
| subscriptions | 5,000 | 14 | `subscription_id` → `account_id` |
| feature_usage | 25,000 | 8 | `usage_id` (**not unique**: 21 values repeat) → `subscription_id` |
| support_tickets | 2,000 | 9 | `ticket_id` → `account_id` |
| churn_events | 600 | 9 | `churn_event_id` → `account_id` |

## 3. Important columns

* **Accounts:** industry, country, `referral_source`, `plan_tier`, `seats`, `is_trial`, `churn_flag`
* **Subscriptions:** `start_date`/`end_date`, plan, seats, `mrr_amount` (always seats × $19/$49/$199), `billing_frequency`, upgrade/downgrade/churn flags
* **Usage:** 40 features with `usage_count`, `usage_duration_secs`, `error_count`, `is_beta_feature`
* **Tickets:** priority, first-response and resolution time, `satisfaction_score`, `escalation_flag`
* **Churn events:** `reason_code`, `refund_amount_usd`, `is_reactivation`, `feedback_text`

## 4. Relationships

Referential integrity is complete (0 orphan keys). Every account has at least one subscription. Data spans 2023-01-01 to 2024-12-31, so the snapshot date is 2024-12-31.

## 5. Data-quality issues found

* **Usage and ticket dates are not aligned with lifecycles:** 76.6% of usage precedes its subscription start, 52.8% precedes account signup, and 53.9% of tickets precede signup.
* **The two churn sources contradict each other:** `churn_flag` marks 110 accounts, `churn_events` covers 352, and they conflict for 312 accounts.
* **Account attributes don't reconcile to subscription history:** `accounts.plan_tier` matches the first subscription for 33% of accounts.
* **Upgrade flags are unreliable:** `upgrade_flag` doesn't track tier changes, and 23 subscriptions carry both upgrade and downgrade flags.
* **Duplicates:** 21 reused `usage_id`s, 3 same-day usage pairs, 1 repeated churn event.
* **Implausible values:** 36 tickets with first response slower than resolution; satisfaction scores only 3–5; 13 zero-day subscriptions.

## 6. Supported analyses

KPIs (MRR, ARR, ARPA, revenue per seat, account/subscription/MRR churn, trial-to-paid, feature adoption, support) · trial and expansion funnels by plan, channel, industry and signup quarter · feature adoption and intensity · rule-based engagement segments · subscription survival (D1–D90, monthly cohorts) and account time to first churn event · churn drivers with statistical tests · a small supporting churn model.

## 7. Not supported (and the replacement)

| Planned | Why not | Replacement |
|---|---|---|
| Users, DAU/MAU | No user table | Accounts; seats as licensed users |
| Onboarding / activation funnel, activation rate | No such events; usage predates signup | Trial and expansion funnels |
| Activity-based Day-N retention, "Dormant"/"At-Risk" segments | Usage timing unreliable | Subscription survival; account time to first churn event; lifetime engagement segments |
| A/B test | No experiment, variant or exposure fields | Observational comparisons plus a hypothetical design (`EXPERIMENT_DESIGN.md`) |
| Net revenue retention | Expansion revenue not separable | Gross MRR churn |

## 8. Analytical architecture

Raw CSVs → Python cleaning with `dq_*` flags → `dataset/processed` → PostgreSQL (`core` tables with constraints, `analytics` views) → SQL analysis and Python analysis/statistics, reconciled against each other → CSV outputs and figures → Tableau.

## 9. Tableau structure

1. Product & Revenue Overview
2. Feature Adoption & Engagement
3. Retention & Churn

(Specifications: `tableau/README.md`.)

## 10. Implementation steps

1. Scaffold and clean the data
2. Build analysis modules (KPIs, funnel, features, segments, retention, churn)
3. Statistics and churn model
4. PostgreSQL schema, load and SQL analysis
5. Check SQL results against Python
6. Notebooks
7. Documentation, Tableau specs, README
8. Full re-run and audit
