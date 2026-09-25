"""Cohort retention.

Usage dates are not aligned with lifecycles, so activity-based retention is not valid.
Two lifecycle-consistent retention views are used instead (both have daily dates):

1. SUBSCRIPTION retention - cohort = start month; a subscription is retained at day N when
   end_date IS NULL or end_date - start_date >= N. Only subscriptions whose start_date is at
   least N days before the snapshot are eligible (no partially observed windows).
2. ACCOUNT retention to first churn event - cohort = signup month/quarter; an account is
   retained at day N when it has no churn event within N days of signup.

Kaplan-Meier estimates (statsmodels) are reported alongside as a censoring-aware check.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from statsmodels.duration.survfunc import SurvfuncRight

from src.utils.config import PLAN_ORDER, SNAPSHOT_DATE
from src.utils.plotting import ACCENT, ACCENT_FILL, PLAN_COLORS, SEQ_CMAP, save_fig

SUB_WINDOWS = [1, 7, 14, 30, 60, 90]
ACCOUNT_WINDOWS = [30, 60, 90, 180, 365]


def subscription_frame(t: dict[str, pd.DataFrame], af: pd.DataFrame) -> pd.DataFrame:
    s = t["subscriptions"].merge(af[["account_id", "referral_source", "industry", "breadth_quartile", "engagement_segment"]], on="account_id")
    s["days_observable"] = (SNAPSHOT_DATE - s["start_date"]).dt.days
    s["start_quarter"] = s["start_date"].dt.to_period("Q").astype(str)
    return s


def account_frame(af: pd.DataFrame) -> pd.DataFrame:
    a = af.copy()
    a["days_to_first_churn"] = (a["first_churn_date"] - a["signup_date"]).dt.days
    a["days_observable"] = (SNAPSHOT_DATE - a["signup_date"]).dt.days
    a["event"] = a["first_churn_date"].notna()
    a["duration"] = a["days_to_first_churn"].fillna(a["days_observable"])
    return a


def window_retention(df: pd.DataFrame, duration_col: str, event_col: str, windows, by: str | None = None) -> pd.DataFrame:
    """Share retained at each window among units observable for the full window."""
    rows = []
    groups = [("All", df)] if by is None else list(df.groupby(by, observed=True))
    for key, g in groups:
        for n in windows:
            elig = g[g["days_observable"] >= n]
            if elig.empty:
                continue
            retained = ~(elig[event_col] & (elig[duration_col] < n))
            rows.append({"group": str(key), "window_days": n, "eligible": len(elig),
                         "retained": int(retained.sum()), "retention_rate": retained.mean()})
    out = pd.DataFrame(rows)
    if by:
        out.insert(0, "dimension", by)
    return out


def subscription_window_retention(s: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    return window_retention(s, "duration_days", "churn_flag", SUB_WINDOWS, by)


def account_window_retention(a: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    return window_retention(a, "duration", "event", ACCOUNT_WINDOWS, by)


def kaplan_meier(df: pd.DataFrame, duration: str, event: str, times, by: str | None = None) -> pd.DataFrame:
    rows = []
    groups = [("All", df)] if by is None else list(df.groupby(by, observed=True))
    for key, g in groups:
        sf = SurvfuncRight(g[duration].astype(float).values, g[event].astype(int).values)
        for tt in times:
            idx = np.searchsorted(sf.surv_times, tt, side="right") - 1
            rows.append({"group": str(key), "day": tt, "km_survival": 1.0 if idx < 0 else sf.surv_prob[idx], "n": len(g)})
    return pd.DataFrame(rows)


def monthly_cohort_matrix(s: pd.DataFrame, max_months: int = 12) -> pd.DataFrame:
    """Subscription start-month cohorts x months since start. Cells are shown only when every
    subscription in the cohort has been observable for the full k months."""
    records = []
    for cohort, g in s.groupby("start_month"):
        cohort_end = cohort + pd.offsets.MonthEnd(0)
        row = {"cohort": cohort, "cohort_size": len(g)}
        for k in range(0, max_months + 1):
            if cohort_end + pd.DateOffset(months=k) > SNAPSHOT_DATE:
                row[k] = np.nan
                continue
            threshold = g["start_date"] + pd.DateOffset(months=k)
            retained = g["end_date"].isna() | (g["end_date"] >= threshold)
            row[k] = retained.mean()
        records.append(row)
    return pd.DataFrame(records).set_index("cohort")


def quarterly_cohort_retention(s: pd.DataFrame) -> pd.DataFrame:
    r = subscription_window_retention(s, "start_quarter")
    return r.pivot(index="group", columns="window_days", values="retention_rate")


def plot_cohort_heatmap(cm: pd.DataFrame) -> None:
    m = cm.drop(columns="cohort_size")
    m.index = [f"{d:%Y-%m} (n={n})" for d, n in zip(cm.index, cm["cohort_size"])]
    fig, ax = plt.subplots(figsize=(12, 9))
    sns.heatmap(m, cmap=SEQ_CMAP, vmin=0.6, vmax=1.0, annot=True, fmt=".0%", annot_kws={"size": 7}, cbar_kws={"label": "Share of subscriptions still active"}, ax=ax, linewidths=0.4, linecolor="white")
    ax.set(title="Subscription retention by start-month cohort", xlabel="Months since subscription start", ylabel="Start-month cohort (subscriptions)")
    save_fig(fig, "06_cohort_retention_heatmap")


def plot_retention_curves(km_plan: pd.DataFrame, acc_quarter: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for plan in PLAN_ORDER:
        d = km_plan[km_plan["group"] == plan]
        axes[0].plot(d["day"], d["km_survival"], lw=2, color=PLAN_COLORS[plan], label=plan)
    axes[0].yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    axes[0].set(title="Subscription survival by plan (Kaplan-Meier)", xlabel="Days since subscription start", ylabel="Still active")
    axes[0].legend(frameon=False)
    d = acc_quarter[(acc_quarter["window_days"] == 180) & (acc_quarter["eligible"] >= 20)].sort_values("group")
    axes[1].bar(d["group"], d["retention_rate"], color=ACCENT_FILL, edgecolor=ACCENT, linewidth=0.6)
    axes[1].axhline(d["retained"].sum() / d["eligible"].sum(), color=ACCENT, lw=1, ls="--")
    axes[1].yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    axes[1].set(title="Accounts with no churn event within 180 days of signup\n(signup quarters with >= 20 eligible accounts; dashed = pooled)", ylabel="Retained at day 180")
    axes[1].tick_params(axis="x", rotation=45)
    save_fig(fig, "07_retention_curves")
