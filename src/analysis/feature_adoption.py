"""Feature adoption, usage intensity and friction.

Adoption rate (feature F) = accounts with >=1 usage event of F / total accounts.
Usage events link to accounts through subscription_id -> subscriptions.account_id.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from src.utils.config import PLAN_ORDER
from src.utils.plotting import (ACCENT, ACCENT_FILL, ALERT, ALERT_FILL, NEUTRAL, NEUTRAL_FILL,
                                SEQ_CMAP, save_fig)


def usage_with_accounts(t: dict[str, pd.DataFrame], af: pd.DataFrame) -> pd.DataFrame:
    u = t["feature_usage"].merge(
        t["subscriptions"][["subscription_id", "account_id", "plan_tier"]].rename(columns={"plan_tier": "subscription_plan_tier"}),
        on="subscription_id")
    return u.merge(af[["account_id", "industry", "engagement_segment"]], on="account_id")


def feature_summary(u: pd.DataFrame, n_accounts: int) -> pd.DataFrame:
    g = u.groupby("feature_name")
    s = g.agg(adopting_accounts=("account_id", "nunique"), usage_events=("usage_row_id", "size"),
              total_usage_count=("usage_count", "sum"), total_duration_secs=("usage_duration_secs", "sum"),
              total_errors=("error_count", "sum"), beta_event_share=("is_beta_feature", "mean"))
    s["adoption_rate"] = s["adopting_accounts"] / n_accounts
    s["events_per_adopting_account"] = s["usage_events"] / s["adopting_accounts"]
    s["usage_count_per_adopting_account"] = s["total_usage_count"] / s["adopting_accounts"]
    s["avg_minutes_per_event"] = s["total_duration_secs"] / s["usage_events"] / 60
    s["errors_per_100_uses"] = 100 * s["total_errors"] / s["total_usage_count"]
    s["adoption_rank"] = s["adoption_rate"].rank(ascending=False, method="min").astype(int)
    hi_adopt = s["adoption_rate"] >= s["adoption_rate"].median()
    hi_int = s["usage_count_per_adopting_account"] >= s["usage_count_per_adopting_account"].median()
    s["adoption_quadrant"] = np.select(
        [hi_adopt & hi_int, ~hi_adopt & hi_int, hi_adopt & ~hi_int],
        ["Core (broad & intensive)", "Underutilized (narrow but intensive)", "Broad but light"], default="Low traction")
    return s.drop(columns="total_duration_secs").sort_values("adoption_rate", ascending=False).reset_index()


def adoption_matrix(u: pd.DataFrame, dim: str, order=None) -> pd.DataFrame:
    """Share of accounts in each group (with usage in that group) that used each feature."""
    base = u.groupby(dim, observed=True)["account_id"].nunique()
    used = u.groupby([dim, "feature_name"], observed=True)["account_id"].nunique().unstack(0)
    m = used.div(base, axis=1)
    return m[order] if order else m


def plan_usage_profile(u: pd.DataFrame, subs: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("subscription_plan_tier")
    p = g.agg(usage_events=("usage_row_id", "size"), subscriptions_with_usage=("subscription_id", "nunique"),
              accounts_with_usage=("account_id", "nunique"), total_usage_count=("usage_count", "sum"),
              total_errors=("error_count", "sum"), avg_minutes_per_event=("usage_duration_secs", lambda x: x.mean() / 60))
    p["subscriptions"] = subs.groupby("plan_tier").size()
    p["events_per_subscription"] = p["usage_events"] / p["subscriptions"]
    p["distinct_features_per_subscription"] = u.groupby(["subscription_plan_tier", "subscription_id"])["feature_name"].nunique().groupby(level=0).mean()
    p["errors_per_100_uses"] = 100 * p["total_errors"] / p["total_usage_count"]
    return p.reindex(PLAN_ORDER).reset_index().rename(columns={"subscription_plan_tier": "plan_tier"})


def beta_comparison(u: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("is_beta_feature")
    b = g.agg(usage_events=("usage_row_id", "size"), mean_usage_count=("usage_count", "mean"),
              mean_minutes=("usage_duration_secs", lambda x: x.mean() / 60), mean_errors_per_event=("error_count", "mean"),
              share_events_with_error=("error_count", lambda x: (x > 0).mean()))
    b["errors_per_100_uses"] = 100 * g["error_count"].sum() / g["usage_count"].sum()
    return b.reset_index()


def monthly_usage(u: pd.DataFrame) -> pd.DataFrame:
    m = u.groupby("usage_month").agg(usage_events=("usage_row_id", "size"), accounts_with_usage=("account_id", "nunique"),
                                     features_used=("feature_name", "nunique"), beta_event_share=("is_beta_feature", "mean"),
                                     total_usage_count=("usage_count", "sum"), total_errors=("error_count", "sum"))
    m["errors_per_100_uses"] = 100 * m["total_errors"] / m["total_usage_count"]
    m["in_subscription_window_share"] = u.groupby("usage_month")["is_in_subscription_window"].mean()
    return m.reset_index()


def plot_feature_adoption(fs: pd.DataFrame) -> None:
    d = fs.sort_values("adoption_rate")
    fig, axes = plt.subplots(1, 2, figsize=(13, 9), gridspec_kw={"width_ratios": [1, 1]})
    n = len(d)
    colors = [ALERT_FILL if i < 5 else (ACCENT_FILL if i >= n - 5 else NEUTRAL_FILL) for i in range(n)]
    edges = [ALERT if i < 5 else (ACCENT if i >= n - 5 else NEUTRAL) for i in range(n)]
    axes[0].barh(d["feature_name"], d["adoption_rate"], color=colors, edgecolor=edges, linewidth=0.6)
    axes[0].axvline(d["adoption_rate"].mean(), color="black", lw=0.8, ls="--")
    axes[0].set_xlim(d["adoption_rate"].min() * 0.9, d["adoption_rate"].max() * 1.03)
    axes[0].xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    axes[0].set(title="Account adoption rate by feature\n(top 5 blue, bottom 5 red; dashed = mean; axis truncated)", xlabel="Share of accounts")
    quad_colors = {"Core (broad & intensive)": ACCENT, "Underutilized (narrow but intensive)": ALERT,
                   "Broad but light": NEUTRAL, "Low traction": "#D4D4D4"}
    for q, dq in fs.groupby("adoption_quadrant"):
        axes[1].scatter(dq["adoption_rate"], dq["usage_count_per_adopting_account"], s=60, color=quad_colors[q], label=q, edgecolor="white")
    for _, r in fs.iterrows():
        axes[1].annotate(r["feature_name"].replace("feature_", "f"), (r["adoption_rate"], r["usage_count_per_adopting_account"]), fontsize=7, xytext=(3, 2), textcoords="offset points")
    axes[1].axvline(fs["adoption_rate"].median(), color="grey", lw=0.8, ls=":")
    axes[1].axhline(fs["usage_count_per_adopting_account"].median(), color="grey", lw=0.8, ls=":")
    axes[1].xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    axes[1].set(title="Adoption breadth vs intensity (lines = medians)", xlabel="Adoption rate", ylabel="Usage count per adopting account")
    axes[1].legend(frameon=False, fontsize=8, loc="upper right")
    save_fig(fig, "04_feature_adoption")


def plot_adoption_heatmap(matrix: pd.DataFrame, title: str, fname: str) -> None:
    m = matrix.loc[matrix.mean(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(6, 11))
    sns.heatmap(m, cmap=SEQ_CMAP, annot=True, fmt=".0%", annot_kws={"size": 7}, cbar=False, ax=ax, linewidths=0.4, linecolor="white")
    ax.set(title=title, xlabel="", ylabel="")
    save_fig(fig, fname)


def plot_monthly_usage(mu: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.plot(mu["usage_month"], mu["accounts_with_usage"], color=ACCENT, lw=2, label="Accounts with usage")
    ax2 = ax.twinx()
    ax2.bar(mu["usage_month"], mu["usage_events"], width=20, color=NEUTRAL_FILL, label="Usage events")
    ax2.grid(False)
    ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
    ax.set(title="Monthly product usage (calendar month of usage_date)", ylabel="Accounts with usage")
    ax2.set_ylabel("Usage events")
    ax.set_ylim(0, 500)
    save_fig(fig, "05_monthly_usage")
