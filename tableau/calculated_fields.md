# Tableau Calculated Fields

Fields as built in `SaaS Project.twb`, connected to the CSV extracts in `outputs/tables/tableau/`.

**Booleans arrive as text.** The extracts write `true` / `false`, and Tableau's CSV connector types those columns as strings, so `INT([Churn Flag])` returns NULL and `SUM` of it is blank. Every boolean measure therefore uses the `IF [field] = "true" THEN 1 ELSE 0 END` form. (Against the PostgreSQL views the columns are real booleans and `INT()` works — the formulas differ by data source.)

**Rates are ratios of sums**, never averages of pre-computed rates, so they stay correct under any filter.

---

## Dashboard 1 · Product & Revenue Overview

| Field | Formula | Source | Result |
|---|---|---|---|
| Total Accounts | `COUNTD([account_id])` | account_features | 500 |
| MRR (Latest) | `SUM([mrr])` with a filter of Month = latest | monthly_kpis | $10.16M |
| ARPA (Latest) | `SUM([mrr]) / SUM([paying_accounts])` | monthly_kpis | $20,319 |
| Revenue per Paid Seat | `SUM([mrr]) / SUM([paid_seats])` | monthly_kpis | $89.58 |
| Trial-to-Paid Conversion | `SUM(IF [trial_converted] = "true" THEN 1 ELSE 0 END) / SUM(IF [has_trial_subscription] = "true" THEN 1 ELSE 0 END)` | account_features | 94.29% |
| Avg Subscription Churn (24 mo) | `AVG([subscription_churn_rate])` | monthly_kpis | 0.87% |
| Avg Churn 2024 | `AVG([subscription_churn_rate])` filtered to 2024 | monthly_kpis | 1.25% |
| Funnel Step Conversion | `SUM([accounts]) / LOOKUP(SUM([accounts]), -1)` | funnel_overall | table calc along Stage |

> **Delete the unused `Try` field.** `SUM(INT([trial_converted])) / SUM(INT([has_trial_subscription]))` returns NULL on this data source for the string-boolean reason above. `Trial-to-Paid Conversion` is the working version.

> **The two churn tiles cover different windows.** 0.87% averages all 24 months (including four months with no ended subscriptions at the start of 2023); 1.25% averages 2024 only. Keep both only with the windows named in the tile captions, as above.

---

## Dashboard 2 · Feature Adoption & Engagement

| Field | Formula | Source | Result |
|---|---|---|---|
| Mean Feature Adoption | `AVG([adoption_rate])` | feature_summary | 69.0% |
| Median Features per Account | `MEDIAN([distinct_features])` | account_features | 28 |
| Errors per 100 Uses | `100 * SUM([errors]) / SUM([usage_count])` | feature_usage_monthly | 5.63 |
| Engagement Share by Channel | `SUM(IF [engagement_segment] IN ('Power Accounts','Engaged Accounts') THEN 1 ELSE 0 END) / COUNTD([account_id])` | account_features | 46.6%–53.1% by channel |
| ColorStart (parameter) | `0.466019417` | — | lowest channel share, anchors the diverging colour ramp |

**Formatting:** set Mean Feature Adoption to Percentage (1 dp) — it currently reads `0.69`, and every other rate tile on the workbook is a percentage.

**Monthly Usage Trend** draws from `usage_monthly_overall.csv` (one row per month):

| Field | Formula | Result |
|---|---|---|
| Monthly Active Accounts | `SUM([accounts_with_usage])` | 409–440 per month |
| Monthly Usage Events | `SUM([usage_events])` | ~1,000–1,400 per month |

It cannot come from `feature_usage_monthly.csv`, which is one row per **feature × month**: `COUNTD([accounts])` there counts distinct *values of a count column*, and `SUM([accounts])` would count each account once per feature it used.

---

## Dashboard 3 · Retention & Churn

| Field | Formula | Source | Result |
|---|---|---|---|
| Account Churn Rate | `SUM(IF [churn_flag] = "true" THEN 1 ELSE 0 END) / COUNTD([account_id])` | account_features | 22.00% |
| ≥1 Churn Event | `SUM(IF [has_churn_event] = "true" THEN 1 ELSE 0 END) / COUNTD([account_id])` | account_features | 70.40% |
| D30 Retention | `SUM(IF [window_days] = 30 AND [dimension] = 'overall' THEN [retained] END) / SUM(IF [window_days] = 30 AND [dimension] = 'overall' THEN [eligible] END)` | subscription_retention_windows | 97.44% |
| D90 Retention | same with `[window_days] = 90` | subscription_retention_windows | 95.84% |
| Account D90 without Churn Event | same with `[window_days] = 90` | account_retention_windows | 68.48% |
| Reactivation Share | `SUM(IF [is_reactivation] = "true" THEN 1 ELSE 0 END) / COUNTD([churn_event_id])` | churn_events_enriched | 10.18% |

> Reactivation is a property of a churn **event**, so the denominator is the 599 events, not the 352 distinct accounts that churned. Dividing by accounts would overstate the rate as 17.3%.

### Fields to add for the chart fixes

| Field | Formula | Used by |
|---|---|---|
| Churn Rate (weighted) | `SUM([churned]) / SUM([accounts])` | Account Churn Rate by Segment — correct under any filter, unlike `AVG([churn_rate])` |
| Overall Churn Rate | `{FIXED : SUM([churned]) / SUM([accounts])}` | reference line at 22% |
| Retention Rate (weighted) | `SUM([retained]) / SUM([eligible])` | Retention Rate by Window & Dimension |
| Window Label | `"D" + STR([window_days])` | D1 … D90 axis |
| Cohort Label | `STR(YEAR([cohort])) + "-" + RIGHT("0" + STR(MONTH([cohort])), 2) + " (n=" + STR([cohort_size]) + ")"` | cohort heatmap rows |
| Small Sample Flag | `IF SUM([accounts]) < 30 THEN "n < 30" END` | tooltip warning |

The confidence bounds are already columns in `churn_by_segment.csv` (`ci_low`, `ci_high`, `lift_vs_overall`) — no calculation needed.

---

## Colour palette

| Role | Hex | Applied to |
|---|---|---|
| Accent (blue) | `#BCEAF8` | primary bars, lines, highlighted KPI tiles |
| Alert (salmon) | `#F9D2C8` | MRR area, secondary series, alert tiles |
| Neutral (grey) | `#E6E6E6` | supporting series, neutral tiles |
| Panel background | `#F5F5F5` | dashboard background |
| Ink | `#333333` | titles and labels |

The Python figures in `outputs/figures/` use the same palette, with deeper companions of each hue (`#5FAECB`, `#DE8A6E`, `#AEB6BD`) for thin lines and marker edges, which the pale fills cannot carry on a white page. Defined once in `src/utils/plotting.py`.
