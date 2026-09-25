# Data Quality Report

Produced by `src/data/clean.py` (log: `outputs/tables/data_quality_checks.csv`) and re-verified in PostgreSQL by `sql/02_data_quality.sql`.

**Guiding rule:** no record was deleted. Every anomaly was first judged as either a plausible business case or a data-quality issue. It was then flagged with a `dq_*` column and handled explicitly in each analysis.

> **Context:** RavenStack is a **synthetic** dataset. Several issues below, especially cross-table date misalignment and contradictory churn fields, are consistent with tables that were generated independently. They are documented rather than "fixed", because no correct value can be recovered.

## 1. Summary

| Area | Status |
|---|---|
| Files read | 5 of 5 CSVs, 33,100 rows. Row counts match the dataset README |
| Parsing | All dates parse; no invalid or future dates (max = 2024-12-31) |
| Full-row duplicates | None in any table |
| Referential integrity | Complete: 0 orphan FKs; every account has ≥ 1 subscription; 492 of 500 accounts have tickets |
| Categorical consistency | All values within expected domains; no casing or whitespace variants |
| Impossible numeric values | None negative. 36 tickets have first response slower than resolution |
| Cross-table temporal logic | **Major issue:** usage and ticket dates are not aligned with account or subscription dates |
| Semantic consistency | **Major issue:** account churn_flag contradicts churn_events; account plan_tier contradicts subscription history |

## 2. Missing values

| Table.column | NULL rows | % | Meaning | Decision |
|---|---:|---:|---|---|
| subscriptions.end_date | 4,514 | 90.3% | Subscription still active | Kept NULL; defines active status |
| support_tickets.satisfaction_score | 825 | 41.3% | No survey response | Kept NULL, never imputed; response rate reported as a KPI |
| churn_events.feedback_text | 148 | 24.7% | Optional comment | Kept NULL |

No other column contains NULLs.

## 3. Duplicates

| Check | Result | Assessment | Decision |
|---|---|---|---|
| Full-row duplicates (all tables) | 0 | | |
| Duplicate primary keys: account, subscription, ticket, churn event | 0 | | |
| `feature_usage.usage_id` reused | 21 IDs across 42 rows | The rows differ in every attribute (subscription, date, feature, counts): an **ID collision**, not duplicated records | All 42 kept; surrogate PK `usage_row_id`; flag `dq_duplicate_usage_id` |
| Same subscription + date + feature | 3 pairs (6 rows) | Different counts and durations: plausible separate sessions | Kept + flagged `dq_same_sub_date_feature` |
| Same account + churn_date in churn_events | 1 pair | Same reason (pricing); different refund and feedback. An account cannot churn twice in a day | Second event flagged `dq_duplicate_account_date` and **excluded** from event counts |

## 4. Dates

| Check | Rows | % | Decision |
|---|---:|---:|---|
| Unparseable or future dates | 0 | 0% | |
| subscription end_date < start_date | 0 | 0% | |
| subscription start_date < account signup_date | 0 | 0% | Subscription lifecycle is consistent |
| churn_date < signup_date | 0 | 0% | |
| ticket closed_at < submitted_at | 0 | 0% | resolution_time_hours equals closed − submitted for all rows |
| **usage_date before its subscription start** | 19,142 | 76.6% | Kept + flagged |
| usage_date after its subscription end | 290 | 1.2% | Kept + flagged |
| **usage_date before account signup** | 13,198 | 52.8% | Kept + flagged |
| **ticket submitted before account signup** | 1,077 | 53.9% | Kept + flagged |

**Impact:** usage and tickets are used only as **lifetime behaviour aggregates** per account or subscription. The following are **not** produced, because they would rest on invalid timing:
* activation rate
* time-to-first-use
* usage-based (activity) retention
* "usage in the first N days"
* recency-based "Dormant" or "At-Risk" segments

Monthly active accounts stay flat at 409–440 through 2023–2024, even though 273 of the 500 accounts signed up in 2024. This independently confirms the misalignment.

## 5. Inconsistent semantics between tables

| Issue | Evidence | Decision |
|---|---|---|
| **Two churn sources disagree** | `churn_flag` TRUE for 110 accounts; 352 accounts have churn events. 277 accounts with events are not flagged; 35 flagged accounts have no event (312 conflicts, 62.4%) | `churn_flag` = account churn **status** (primary label). `churn_events` = churn **episodes** (reasons, timing, reactivations). Never mixed in one metric; flag `dq_churn_flag_conflict` |
| Churned accounts still pay | All 110 churn-flagged accounts hold active subscriptions on 2024-12-31 ($2,073,153 MRR, 20.4% of total) | Documented; revenue KPIs are "as recorded" |
| `accounts.plan_tier` vs subscriptions | Equals the first subscription's plan for 33.0% of accounts, the latest for 34.4%, the most frequent for 27.4% | Account plan_tier used as a recorded attribute; subscription plan_tier used for billing analyses |
| `accounts.seats` vs subscriptions | Equals the first subscription's seats for 55.2% of accounts | Account seats used only as a descriptive attribute |
| `upgrade_flag` vs actual tier changes | Of 484 upgrade-flagged subscriptions with a prior subscription, 183 moved up a tier, 157 stayed and 144 moved down; 1,303 tier increases carry no flag | Used as a recorded flag only; no claims about upgrade paths |
| Upgrade AND downgrade flags both TRUE | 23 subscriptions | Kept + flagged `dq_upgrade_and_downgrade` |
| `feedback_text` vs `reason_code` | Every reason code occurs with every feedback text in similar proportions (e.g. `budget` + "switched to competitor") | Reason analysis uses `reason_code`; feedback reported but not treated as corroborating |
| `is_beta_feature` | Varies by row for all 40 features (about 10% of rows each) | Treated as an attribute of the usage event, not of the feature |

## 6. Impossible or suspicious values

| Check | Rows | Assessment | Decision |
|---|---:|---|---|
| first_response_time_minutes > resolution time | 36 (1.8%) | Logically impossible | Kept + flagged; excluded from first-response metrics |
| satisfaction_score outside 1–5 | 0 | Only 3, 4, 5 occur (396 / 405 / 374): no dissatisfied responses at all | Kept; CSAT is noted as uninformative about dissatisfaction |
| 0-day subscriptions (end = start) | 13 | Same-day cancellation is plausible | Kept + flagged `dq_zero_duration` |
| usage_count = 0 | 2 | Duration is also 0: consistent empty session | Kept + flagged |
| MRR ≠ seats × list price | 0 | Deterministic pricing: Basic $19, Pro $49, Enterprise $199 per seat per month; trials $0 | Used as a validation rule (CHECK constraint in SQL) |
| ARR ≠ 12 × MRR | 0 | | CHECK constraint |

## 7. Outliers (IQR rule: > Q3 + 1.5 × IQR)

| Column | Outliers | Assessment | Decision |
|---|---:|---|---|
| accounts.seats | 25 (5.0%) | Right-skewed; max 163 seats is plausible for a larger customer | Kept |
| subscriptions.mrr_amount | 471 (9.4%) | Fully explained by seats × Enterprise price | Kept |
| feature_usage.usage_duration_secs | 145 (0.6%) | Max 12,696 s (3.5 h) is a plausible session | Kept |

Medians and rank-based tests (Mann-Whitney) are used where distributions are skewed, so outliers are not removed.

## 8. Distributional patterns to keep in mind

* **Back-loaded activity.** Subscription starts rise from 31 (2023Q1) to 2,069 (2024Q4); churn events from 6 to 250 per quarter, or 10.9 → 50.0 per 100 signed-up accounts. Calendar time therefore confounds cohort comparisons.
* **Concurrent subscriptions.** On the snapshot date, accounts hold 9.0 active subscriptions on average (4,514 in total). MRR sums these line items, so MRR grows about 8× during 2024.
* **Every account is paying.** All 500 accounts have at least one paid subscription, and 403 also had a trial, so "trial" is not a gate to "paid".

## 9. Cleaning outputs

`dataset/processed/*.csv` has the five cleaned tables with typed columns, derived fields and `dq_*` flags, plus `account_features.csv`. It is loaded into PostgreSQL `core.*` by `python -m src.data.load_postgres`. `sql/02_data_quality.sql` recomputes every flag in SQL and compares the counts (`flag_matches` column).
