# Tableau Dashboards

**Workbook:** `SaaS Project.twb` — three dashboards built on the CSV extracts in `outputs/tables/tableau/`.
Calculated fields: [calculated_fields.md](calculated_fields.md).

---

## 1 · Product & Revenue Overview

![Product & Revenue Overview](screenshots/01_product_revenue_overview.png)

**Question:** how big is the business, is it growing, and where does the customer journey leak?

| Zone | Chart | Data source |
|---|---|---|
| KPI tiles | Total Accounts 500 · MRR $10.2M · ARPA $20.3K · Revenue per Paid Seat $89.58 · Trial Conversion 94.29% · Subscription Churn 0.87% · Avg Churn 2024 1.25% | monthly_kpis, account_features |
| A | Trial Funnel Conversion by Stage (bars + step conversion) | funnel_overall |
| B | Subscription and Gross MRR Churn Rate by Month (dual line) | monthly_kpis |
| C | New Accounts by Month (line) | monthly_kpis |
| D | MRR by Month (area) | monthly_kpis |

A "Paying Accounts" tile is deliberately absent: every account holds an active paid subscription, so it would always read 100%.

## 2 · Feature Adoption & Engagement

![Feature Adoption & Engagement](screenshots/02_feature_adoption_engagement.png)

**Question:** which features and behaviours define engaged customers?

| Zone | Chart | Data source |
|---|---|---|
| KPI tiles | Mean Feature Adoption 0.69 · Median Features per Account 28 · Errors per 100 Uses 5.63 | feature_summary, account_features, feature_usage_monthly |
| A | Feature Adoption by Plan Tier | feature_adoption_by_plan |
| B | Feature Adoption vs Usage Intensity (scatter) | feature_summary |
| C | Engagement Segment & Churn (stacked bars) | account_features |
| D | Monthly Usage Trend (accounts line + usage-event bars) | usage_monthly_overall |
| E | Engagement Share by Channel (treemap) | account_features |
| F | Feature Adoption Rate (Ranked) | feature_summary |

## 3 · Retention & Churn

![Retention & Churn](screenshots/03_retention_churn.png)

**Question:** who churns, when, and why?

| Zone | Chart | Data source |
|---|---|---|
| KPI tiles | Account Churn 22.00% · ≥1 Churn Event 70.40% · D30 97.44% · D90 95.84% · Account D90 w/o Churn Event 68.48% · Reactivation Share 10.18% | account_features, retention windows, churn_events_enriched |
| A | Churn Reasons & Events by Quarter (stacked area) | churn_events_enriched |
| B | Account Churn Rate by Segment (bars with 95% CI labels) | churn_by_segment |
| C | Retention Rate by Window & Top 3 Dimension | subscription_retention_windows |
| D | Subscription Retention by Cohort | subscription_cohort_retention_long |
| E | Churned vs Retained Profiles (median comparison) | account_features |

---

## Outstanding fixes

Numbers on the tiles and in the funnel are correct. What remains is chart form: two sheets still draw a shape that misstates the measure, and three are cosmetic.

### 1. Retention rates are stacked (Dashboard 3, zone C)

Three segments' retention rates are stacked into one bar, so each column totals ~3.0 — adding retention percentages has no meaning.

**Fix:** mark type **Line**, `group` on Colour, `window_days` on Columns, `Retention Rate (weighted)` on Rows. One line per segment, Y axis 0–100%.

### 2. The cohort sheet is not a cohort view (Dashboard 3, zone D)

It plots `SUM(months_since_start)` and `SUM(retention_rate)` against calendar cohort date. The descending line is just the sum of month offsets shrinking as newer cohorts have fewer observed months — it is not retention.

**Fix:** mark type **Square**; `cohort` on Rows, `months_since_start` on Columns, `AVG(retention_rate)` on Colour, labels as percentages. Unobservable cells must stay blank, not zero. Compare with `outputs/figures/06_cohort_retention_heatmap.png`.

### 3. Plan-tier adoption is stacked (Dashboard 2, zone A)

Basic 0.35 + Pro 0.34 + Enterprise 0.34 are three independent adoption rates, not parts of a whole, so the stacked bar and its "1.03" total are meaningless.

**Fix:** use the long-form `feature_adoption_by_plan.csv` (feature_name, plan_tier, adoption_rate) as a heatmap — `feature_name` on Rows, `plan_tier` on Columns, `AVG(adoption_rate)` on Colour — or side-by-side bars.

### 4. "Ranked" adoption is an unranked line (Dashboard 2, zone F)

A line across `feature_1 … feature_40` implies a trend between features that does not exist, and the axis is in name order, not rank order.

**Fix:** horizontal bars sorted by `adoption_rate` descending, with a mean reference line at 69%.

### 5. Smaller items

* **Mean Feature Adoption** shows `0.69` — format as a percentage (69.0%), like every other rate tile.
* Delete the unused **`Try`** field: `SUM(INT([trial_converted])) / SUM(INT([has_trial_subscription]))` returns NULL on string booleans. `Trial-to-Paid Conversion` is the working version.
* **Account Churn Rate by Segment** mixes plan tiers, channels and industries in one alphabetical list. Put `dimension` on Rows to group them (or add a dimension parameter), sort by churn rate descending, and add a reference line at the 22% overall rate.
* **Churn Reasons & Events by Quarter** is plotted by month. Either aggregate the date to quarter or retitle it "by Month".
* **Feature Adoption vs Usage Intensity** colours 40 points by feature name, which carries no information. Colour by `adoption_quadrant` instead and move `feature_name` to the tooltip.
* Two x-axes start at **Dec '22**, before any data exists — fix the axis range.

---

## Rebuilding the data

```bash
python -m src.run_analysis      # writes outputs/tables/tableau/*.csv
```

All 13 extracts are reconciled against the PostgreSQL views by `python -m src.data.validate_sql_vs_python`.

**Live connection instead of CSVs:** `python -m src.data.load_postgres && python -m src.data.run_sql`, then connect Tableau to PostgreSQL (`localhost`, port `2110`, database `ravenstack`) and use the `analytics.*` views. Booleans are then real booleans, so `INT()` works in place of the `= "true"` comparisons.

## Design system

1200 × 850 fixed layout: title, a KPI tile row, then a chart grid. Palette is one accent (`#BCEAF8`), one alert (`#F9D2C8`) and one neutral (`#E6E6E6`) on a `#F5F5F5` ground, with `#333333` text. Titles are statements; every dashboard carries the note that findings are observational and the data is synthetic.
