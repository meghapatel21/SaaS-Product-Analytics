"""Reconcile PostgreSQL results with the Python analysis (same metric, two implementations).

    python -m src.data.validate_sql_vs_python

Writes outputs/tables/sql_python_reconciliation.csv and exits non-zero on any mismatch.
"""
import json
import sys

import numpy as np
import pandas as pd

from src.utils.config import INSIGHTS_DIR, TABLES_DIR

SQL = TABLES_DIR / "sql"
TOL = 1e-6


def _norm_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r" 00:00:00$", "", regex=True).str.lower().str.strip()


def compare(name, sql_df, py_df, keys, cols, sql_keys=None) -> dict:
    sql_keys = sql_keys or keys
    a = sql_df.rename(columns=dict(zip(sql_keys, keys))).copy()
    b = py_df.copy()
    for k in keys:
        a[k], b[k] = _norm_key(a[k]), _norm_key(b[k])
    m = a[keys + cols].merge(b[keys + cols], on=keys, how="outer", suffixes=("_sql", "_py"), indicator=True)
    unmatched = int((m["_merge"] != "both").sum())
    m = m[m["_merge"] == "both"]
    max_diff, mismatches = 0.0, 0
    for c in cols:
        x, y = m[f"{c}_sql"], m[f"{c}_py"]
        num_x, num_y = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
        if num_x.notna().any() or num_y.notna().any():
            both_nan = num_x.isna() & num_y.isna()
            diff = (num_x.astype(float) - num_y.astype(float)).abs().where(~both_nan, 0.0)
            max_diff = max(max_diff, float(diff.fillna(np.inf).max()) if len(diff) else 0.0)
            mismatches += int((diff.fillna(np.inf) > TOL).sum())
        else:
            mismatches += int((_norm_key(x) != _norm_key(y)).sum())
    return {"check": name, "rows_compared": len(m), "unmatched_keys": unmatched, "value_mismatches": mismatches,
            "max_abs_diff": max_diff, "passed": unmatched == 0 and mismatches == 0}


def main() -> int:
    r = lambda n: pd.read_csv(SQL / f"{n}.csv")
    p = lambda n: pd.read_csv(TABLES_DIR / f"{n}.csv")
    checks = []

    checks.append(compare("monthly KPIs", r("03_product_kpis__kpi_monthly"), p("monthly_kpis"), ["month"],
                          ["new_accounts", "cumulative_accounts", "active_subscriptions", "paying_accounts", "paid_seats", "mrr",
                           "arpa", "ended_subscriptions_from_base", "subscription_churn_rate", "gross_mrr_churn_rate", "churn_events"]))

    snap = r("03_product_kpis__kpi_snapshot").iloc[0]
    head = p("headline_kpis").set_index("metric")["value"]
    mapping = {
        "Total accounts": "total_accounts", "New accounts 2023": "new_accounts_2023", "New accounts 2024": "new_accounts_2024",
        "Active subscriptions at snapshot": "active_subscriptions_at_snapshot",
        "MRR at snapshot ($)": "mrr_at_snapshot", "ARR at snapshot ($)": "arr_at_snapshot", "ARPA ($/month)": "arpa",
        "Revenue per paid seat ($/month)": "revenue_per_paid_seat", "Accounts that ever started a trial": "trial_accounts",
        "Trial-to-paid conversion rate": "trial_to_paid_conversion_rate", "Account churn rate (churn_flag)": "account_churn_rate",
        "Logo retention rate (1 - account churn)": "logo_retention_rate", "Accounts with >=1 churn event": "accounts_with_churn_event_rate",
        "Reactivation share of churn events": "reactivation_share", "Lifetime subscription churn rate": "lifetime_subscription_churn_rate",
        "Avg monthly subscription churn rate 2024": "avg_monthly_subscription_churn_2024",
        "Avg monthly gross MRR churn rate 2024": "avg_monthly_gross_mrr_churn_2024",
        "Subscription upgrade rate": "subscription_upgrade_rate", "Subscription downgrade rate": "subscription_downgrade_rate",
        "Mean feature adoption rate (40 features)": "mean_feature_adoption_rate", "Median distinct features per account": "median_distinct_features",
        "Tickets per account": "tickets_per_account",
        "Escalation rate": "escalation_rate", "CSAT response rate": "csat_response_rate", "Average CSAT (1-5, responders)": "avg_csat",
        "Median resolution time (hours)": "median_resolution_hours", "Median first response (minutes)": "median_first_response_minutes",
    }
    sdf = pd.DataFrame({"metric": list(mapping), "value": [snap[v] for v in mapping.values()]})
    checks.append(compare("headline KPIs", sdf, head.reset_index(), ["metric"], ["value"]))

    checks.append(compare("funnels (overall)", r("04_funnel_analysis__funnel_overall"), p("funnel_overall"), ["funnel", "stage"], ["accounts", "step_conversion"]))
    checks.append(compare("funnels by segment", r("04_funnel_analysis__funnel_by_segment"), p("funnel_by_segment"),
                          ["funnel", "dimension", "segment", "stage"], ["accounts", "step_conversion"]))
    checks.append(compare("feature summary", r("05_feature_adoption__feature_summary"), p("feature_summary"), ["feature_name"],
                          ["adopting_accounts", "usage_events", "adoption_rank", "errors_per_100_uses", "avg_minutes_per_event", "adoption_quadrant"]))
    checks.append(compare("segment profile", r("06_user_segmentation__segment_profile"), p("segment_profile"), ["engagement_segment"],
                          ["accounts", "median_usage_count", "median_distinct_features", "churn_rate", "mrr_at_snapshot"]))
    key_metrics = json.loads((INSIGHTS_DIR / "key_metrics.json").read_text(encoding="utf-8"))
    py_th = pd.Series(key_metrics["segment_thresholds"]).rename_axis("k").reset_index(name="v")
    sql_th = r("06_user_segmentation__segment_thresholds").melt(var_name="k", value_name="v")
    checks.append(compare("segment thresholds", sql_th, py_th, ["k"], ["v"]))

    py_sub = p("subscription_retention_windows").rename(columns={"group": "segment"})
    sql_sub = r("07_cohort_retention__subscription_retention_windows")
    checks.append(compare("subscription retention windows", sql_sub, py_sub[py_sub["dimension"].isin(sql_sub["dimension"].unique())],
                          ["dimension", "segment", "window_days"], ["eligible", "retained", "retention_rate"]))
    py_acc = p("account_retention_windows").rename(columns={"group": "segment"})
    checks.append(compare("account retention windows", r("07_cohort_retention__account_retention_windows"), py_acc,
                          ["dimension", "segment", "window_days"], ["eligible", "retained", "retention_rate"]))
    checks.append(compare("cohort retention matrix", r("07_cohort_retention__cohort_retention_long"),
                          pd.read_csv(TABLES_DIR / "tableau" / "subscription_cohort_retention_long.csv"),
                          ["cohort", "months_since_start"], ["retention_rate", "cohort_size"]))
    checks.append(compare("churn by segment", r("08_churn_analysis__churn_by_segment"), p("churn_by_segment"),
                          ["dimension", "segment"], ["accounts", "churned", "churn_rate", "lift_vs_overall"]))
    checks.append(compare("churn reasons", r("08_churn_analysis__churn_reasons"), p("churn_reasons"), ["reason_code"],
                          ["events", "accounts", "share_of_events", "total_refund_usd", "reactivation_share"]))

    out = pd.DataFrame(checks)
    out.to_csv(TABLES_DIR / "sql_python_reconciliation.csv", index=False)
    print(out.to_string(index=False))
    return 0 if out["passed"].all() else 1


if __name__ == "__main__":
    sys.exit(main())
