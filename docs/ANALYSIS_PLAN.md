# Analysis Plan & Metric Definitions

## 1. Questions and approach

| # | Business question | Approach used | Where |
|---|---|---|---|
| 1 | How do customers move through the funnel? | Account-level trial and expansion funnels built from states that exist | `sql/04`, `src/analysis/funnel.py` |
| 2 | Where do they drop off? | Step conversion / drop-off by plan, channel, industry and signup quarter; largest step = bottleneck | same |
| 3 | Which features are most and least adopted? | Account adoption rate, intensity, errors; breadth-vs-intensity quadrant | `sql/05`, `src/analysis/feature_adoption.py` |
| 4 | Which behaviours go with stronger engagement? | Rule-based engagement segments, friction overlay; clustering sanity check | `sql/06`, `src/analysis/segmentation.py` |
| 5 | How does retention vary across cohorts? | Subscription survival (D1–D90, monthly cohort heatmap); account time to first churn event | `sql/07`, `src/analysis/retention.py` |
| 6 | Which patterns are associated with churn? | Churn rate by 17 dimensions with Wilson CIs and chi-square + Holm; churned vs retained distributions; reasons | `sql/08`, `src/analysis/churn.py` |
| 7 | How do plans and segments perform? | MRR, subscriptions, churn and retention by plan / channel / industry / segment | `sql/03`, `sql/06`–`08` |
| 8 | What should the business do? | Insights tied to calculated evidence | `sql/09`, `docs/BUSINESS_INSIGHTS.md` |

**Unit of analysis:** the account (no user table). **Snapshot:** 2024-12-31. **Language:** all findings are associations. None is causal, and no A/B test exists.

## 2. Core conventions

* **Active subscription at date d:** `start_date <= d AND (end_date IS NULL OR end_date > d)`
* **Start-of-month base:** subscriptions active at the end of the previous month
* **Account churn label:** `accounts.churn_flag`. **Churn episodes:** `churn_events` (repeated same-day event excluded)
* **Retention eligibility:** a unit counts at window N only if observed for at least N days before the snapshot, so partial windows never deflate rates

## 3. KPI definitions (values as of 2024-12-31)

| KPI | Definition | Formula | Why it matters | Value | Computed in |
|---|---|---|---|---:|---|
| Total accounts | Customer accounts ever created | `COUNT(account_id)` | Size of customer base | 500 | SQL 03 · Python kpis |
| New accounts | Accounts created in a period | `COUNT(*) BY signup_month` | Acquisition trend | 227 (2023), 273 (2024) | SQL 03 · Python |
| Active subscriptions | Subscriptions without end_date | `COUNT(*) WHERE end_date IS NULL` | Contracted line items | 4,514 | SQL 03 · Python |
| MRR | Monthly recurring revenue from active subscriptions | `SUM(mrr_amount) WHERE active` | Primary revenue metric | $10,159,608 | SQL 03 · Python |
| ARR | Annualised MRR | `SUM(arr_amount)` = 12 × MRR | Revenue scale | $121,915,296 | SQL 03 · Python |
| ARPA | Average MRR per paying account | `MRR / paying accounts` | Monetisation per customer | $20,319 | SQL 03 · Python |
| Revenue per paid seat | Closest valid "ARPU" (seats = licensed users) | `MRR / SUM(seats of active paid subs)` | Price realisation per user | $89.58 | SQL 03 · Python |
| Trial-to-paid conversion | Trial accounts that later hold a paid subscription | `accounts with paid sub start >= first trial start / accounts with a trial` | Trial effectiveness | 94.3% (380/403) | SQL 03/04 · Python |
| Account churn rate | Share of accounts with churn_flag | `AVG(churn_flag)` | Logo churn | 22.0% | SQL 03/08 · Python |
| Logo retention rate | Complement of account churn | `1 − account churn rate` | Customer retention | 78.0% | SQL 03 · Python |
| Accounts with a churn event | Accounts with ≥ 1 churn episode | `AVG(has_churn_event)` | Churn incidence incl. reactivated accounts | 70.4% | SQL 03 · Python |
| Reactivation share | Churn events for previously churned accounts | `AVG(is_reactivation)` | Win-back dynamics | 10.2% | SQL 03 · Python |
| Lifetime subscription churn | Subscriptions that ended | `AVG(subscriptions.churn_flag)` | Line-item churn | 9.72% | SQL 03 · Python |
| Monthly subscription churn rate | Ended during month from start-of-month base | `ended_from_base / start_of_month_subscriptions` | Churn velocity | 2024 avg 1.25% (monthly range 0.73%–2.40%) | SQL 03 · Python |
| Gross MRR churn rate | MRR of ended base subscriptions | `churned_mrr_from_base / start_of_month_mrr` | Revenue churn | 2024 avg 1.21% | SQL 03 · Python |
| Subscription retention D1…D90 | Share of eligible subscriptions still active N days after start | `COUNT(end IS NULL OR end−start >= N) / eligible` | Early lifecycle retention | D1 99.8%, D7 98.9%, D14 98.1%, D30 97.4%, D60 96.6%, D90 95.8% | SQL 07 · Python |
| Account retention D30…D365 | Share of eligible accounts with no churn event within N days of signup | `COUNT(first_churn IS NULL OR first_churn−signup >= N) / eligible` | Customer lifetime | D30 83.6%, D90 68.5%, D180 56.1%, D365 41.7% | SQL 07 · Python |
| Upgrade / downgrade rate | Subscriptions with the flag | `AVG(upgrade_flag)`, `AVG(downgrade_flag)` | Expansion / contraction | 10.58% / 4.36% | SQL 03 · Python |
| Feature adoption rate | Accounts using a feature / all accounts | `COUNT(DISTINCT account_id) per feature / 500` | Product-market fit per feature | mean 69.0% (range 65.4%–74.8%) | SQL 05 · Python |
| Feature breadth | Distinct features used per account | `COUNT(DISTINCT feature_name)` | Depth of adoption | median 28 of 40 | SQL 05/06 · Python |
| Errors per 100 uses | Friction | `100 × SUM(error_count) / SUM(usage_count)` | Quality | 5.63 overall | SQL 05 · Python |
| Support KPIs | Tickets per account; escalation rate; CSAT response rate; average CSAT; median resolution; median first response | as named | Service experience | 4.0; 4.75%; 58.75%; 3.98; 35 h; 87 min | SQL 03 · Python |

### Metrics requested but not supported

| Requested metric | Why not supported | Replacement |
|---|---|---|
| Total / active / new **users**, DAU/MAU | No user-level table or login events | Accounts, paying accounts, seats |
| Activation rate | No onboarding or activation events; usage dates predate signup for 52.8% of rows | Trial-to-paid conversion; feature breadth |
| Engagement rate from recent activity | Usage timing unreliable | Rule-based lifetime engagement segments |
| Paying / active accounts as a KPI | Always 100% at the snapshot: every account holds an active paid subscription, so a KPI tile carries no information | Used only as the ARPA denominator and as a monthly trend in `v_kpi_monthly` |
| "Engaged-or-better" account share | Always 50%: the segment rule splits at the median | Segment mix, and churn by segment |
| Net revenue retention | Expansion revenue not separable (upgrade flags unreliable; concurrent line items) | Gross MRR churn rate |
| Day-N activity retention | Usage not aligned with lifecycle | Subscription survival and account time to first churn event |

## 4. Funnels

| Funnel | Stages (each requires the previous) | Rationale |
|---|---|---|
| Trial | Signed up → Started a trial → Converted to paid after trial → Retained (churn_flag = FALSE) | Closest valid version of Signup → Trial → Paid |
| Expansion | Signed up → Paying → Upgraded (any upgrade_flag) → Retained | Monetisation path; "Paying" is 100% by data |

Segmented by plan_tier, referral_source, industry and signup_quarter (conversion over time).

## 5. Segmentation rules (computed thresholds)

| Segment | Rule | Accounts |
|---|---|---:|
| Power Accounts | total_usage_count ≥ 619.25 (P75) AND distinct_features ≥ 32 (P75) | 97 |
| Engaged Accounts | not Power AND total_usage_count ≥ 498.5 (P50) | 153 |
| Casual Accounts | 373 (P25) ≤ total_usage_count < 498.5 | 127 |
| Low-Engagement Accounts | total_usage_count < 373 | 123 |
| high_friction (overlay) | error_rate ≥ 0.0658 (P75) OR ≥ 1 escalated ticket | 187 |

"Dormant" and "At-Risk" were not used because they require reliable recency. K-means on six standardised behavioural features gave a best silhouette of 0.271 (k = 2; k = 3–6: 0.19–0.20), which shows weak structure. Clustering was therefore evaluated but **not adopted**.

## 6. Statistical approach

* alpha = 0.05 applied to Holm-adjusted p-values across the 11-test family. The 17 churn-dimension chi-square tests are Holm-adjusted as their own family, so a dimension such as industry has a different adjusted p-value in the churn-drivers table than in the 11-test family. Raw p-values are always reported next to adjusted ones.
* Tests are chosen by data type:
  * chi-square for categorical × churn (expected counts checked)
  * two-proportion z-test with Newcombe CI and Cohen's h
  * Fisher's exact test for small groups
  * Mann-Whitney U with rank-biserial r and bootstrap median CI for skewed counts
  * log-rank for censored survival
  * Kruskal-Wallis with epsilon-squared for a continuous outcome across more than two groups
* Churn model: logistic regression and random forest; 75/25 stratified split plus 5×5 repeated stratified CV; balanced class weights; leakage-prone features excluded. Reported: ROC-AUC with bootstrap CI, precision, recall, F1, confusion matrix, coefficients and permutation importance.
* **A/B testing:** no experiment fields exist, so observational comparisons are labelled as such. The hypothetical design is in `docs/EXPERIMENT_DESIGN.md`.

## 7. Validation

* Every KPI, funnel, segment, retention and churn table is computed independently in Python and SQL. `python -m src.data.validate_sql_vs_python` compares them (tolerance 1e-6) and writes `outputs/tables/sql_python_reconciliation.csv`.
* Kaplan-Meier estimates are reported next to eligible-cohort retention as a censoring-aware check.
