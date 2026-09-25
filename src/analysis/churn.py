"""Churn drivers analysis (observational, associations only).

Primary churn label: accounts.churn_flag (account churn STATUS).
Churn reasons / timing: churn_events (duplicate account+date event excluded).
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

from src.utils.plotting import ACCENT, ALERT, NEUTRAL, NEUTRAL_FILL, save_fig

CATEGORICAL_DRIVERS = [
    "plan_tier", "highest_plan_tier", "industry", "country", "referral_source", "signup_quarter", "tenure_bucket",
    "engagement_segment", "breadth_quartile", "usage_quartile", "ticket_bucket", "any_escalation", "high_friction",
    "is_trial", "has_trial_subscription", "any_upgrade", "any_downgrade",
]
NUMERIC_DRIVERS = [
    "seats", "tenure_days", "n_subscriptions", "n_upgrades", "n_downgrades", "mrr_at_snapshot", "total_usage_count",
    "distinct_features", "total_duration_hours", "error_rate", "beta_event_share", "n_tickets", "n_escalations",
    "avg_resolution_hours", "avg_first_response_minutes", "avg_satisfaction",
]


def churn_by_dimension(af: pd.DataFrame, dims=CATEGORICAL_DRIVERS) -> tuple[pd.DataFrame, pd.DataFrame]:
    overall = af["churn_flag"].mean()
    rows, tests = [], []
    for dim in dims:
        ct = pd.crosstab(af[dim], af["churn_flag"])
        chi2, p, dof, expected = stats.chi2_contingency(ct)
        n = ct.values.sum()
        cramers_v = np.sqrt(chi2 / (n * (min(ct.shape) - 1)))
        tests.append({"dimension": dim, "chi2": chi2, "dof": dof, "p_value": p, "cramers_v": cramers_v,
                      "min_expected_count": expected.min(), "groups": ct.shape[0]})
        for value, r in ct.iterrows():
            k, tot = int(r.get(True, 0)), int(r.sum())
            lo, hi = proportion_confint(k, tot, method="wilson")
            rows.append({"dimension": dim, "segment": str(value), "accounts": tot, "churned": k,
                         "churn_rate": k / tot, "ci_low": lo, "ci_high": hi, "lift_vs_overall": (k / tot) / overall})
    tests = pd.DataFrame(tests)
    tests["p_holm"] = multipletests(tests["p_value"], method="holm")[1]
    tests["significant_after_holm"] = tests["p_holm"] < 0.05
    return pd.DataFrame(rows), tests.sort_values("p_value")


def numeric_comparison(af: pd.DataFrame, cols=NUMERIC_DRIVERS) -> pd.DataFrame:
    rows = []
    for c in cols:
        ch = af.loc[af["churn_flag"], c].dropna()
        rt = af.loc[~af["churn_flag"], c].dropna()
        u, p = stats.mannwhitneyu(ch, rt, alternative="two-sided")
        rows.append({"feature": c, "median_churned": ch.median(), "median_retained": rt.median(),
                     "mean_churned": ch.mean(), "mean_retained": rt.mean(), "n_churned": len(ch), "n_retained": len(rt),
                     "mann_whitney_u": u, "p_value": p, "rank_biserial": 1 - 2 * u / (len(ch) * len(rt))})
    out = pd.DataFrame(rows)
    out["p_holm"] = multipletests(out["p_value"], method="holm")[1]
    return out.sort_values("p_value")


def churn_reasons(t: dict[str, pd.DataFrame], af: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ce = t["churn_events"]
    ce = ce[~ce["dq_duplicate_account_date"]].merge(af[["account_id", "plan_tier", "referral_source", "churn_flag"]], on="account_id")
    reasons = ce.groupby("reason_code").agg(events=("churn_event_id", "size"), accounts=("account_id", "nunique"),
                                            refund_share=("refund_amount_usd", lambda x: (x > 0).mean()),
                                            total_refund_usd=("refund_amount_usd", "sum"),
                                            preceding_upgrade_share=("preceding_upgrade_flag", "mean"),
                                            preceding_downgrade_share=("preceding_downgrade_flag", "mean"),
                                            reactivation_share=("is_reactivation", "mean"))
    reasons["share_of_events"] = reasons["events"] / reasons["events"].sum()
    by_plan = pd.crosstab(ce["plan_tier"], ce["reason_code"], normalize="index")
    feedback = pd.crosstab(ce["reason_code"], ce["feedback_text"].fillna("(no feedback)"))
    quarterly = ce.groupby([ce["churn_date"].dt.to_period("Q").astype(str), "reason_code"]).size().unstack(fill_value=0)
    return {"reasons": reasons.sort_values("events", ascending=False).reset_index(),
            "reasons_by_plan": by_plan, "reason_vs_feedback": feedback, "events_by_quarter": quarterly}


def plot_churn_drivers(drivers: pd.DataFrame, tests: pd.DataFrame, overall: float, dims: list[str]) -> None:
    d = drivers[drivers["dimension"].isin(dims)].copy()
    d["label"] = d["dimension"].str.replace("_", " ") + ": " + d["segment"]
    d["order"] = d["dimension"].map({k: i for i, k in enumerate(dims)})
    d = d.sort_values(["order", "churn_rate"], ascending=[False, True])
    by_dim = tests.set_index("dimension")
    fig, ax = plt.subplots(figsize=(9, 0.28 * len(d) + 1.5))
    y = np.arange(len(d))
    colors = [ALERT if r > overall * 1.2 else (ACCENT if r < overall * 0.8 else NEUTRAL) for r in d["churn_rate"]]
    ax.hlines(y, d["ci_low"], d["ci_high"], color="#D4D4D4", lw=2)
    ax.scatter(d["churn_rate"], y, color=colors, zorder=3, s=30)
    ax.axvline(overall, color="black", lw=0.8, ls="--")
    ax.set_yticks(y, d["label"], fontsize=8)
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    min_raw, min_holm = by_dim["p_value"].reindex(dims).min(), by_dim["p_holm"].reindex(dims).min()
    verdict = (f"Chi-square per dimension: smallest raw p = {min_raw:.3f}; none significant after Holm correction across all {len(tests)} dimensions"
               if min_holm >= 0.05 else f"Smallest Holm-adjusted p = {min_holm:.3f} (Holm across {len(tests)} dimensions)")
    ax.set(xlabel="Account churn rate (dot) with 95% Wilson CI", title=f"Churn rate by segment (dashed = overall)\n{verdict}")
    save_fig(fig, "08_churn_drivers")


def plot_churn_reasons(reasons: pd.DataFrame, quarterly: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    r = reasons.sort_values("events")
    axes[0].barh(r["reason_code"], r["events"], color=NEUTRAL_FILL, edgecolor=NEUTRAL, linewidth=0.6)
    for i, (e, s) in enumerate(zip(r["events"], r["share_of_events"])):
        axes[0].text(e, i, f" {e} ({s:.0%})", va="center", fontsize=8)
    axes[0].set(title="Churn events by recorded reason", xlabel="Churn events")
    axes[0].set_xlim(0, r["events"].max() * 1.25)
    quarterly.sum(axis=1).plot(ax=axes[1], color=ACCENT, lw=2, marker="o")
    axes[1].set(title="Churn events per quarter", xlabel="", ylabel="Churn events")
    axes[1].tick_params(axis="x", rotation=45)
    save_fig(fig, "09_churn_reasons")
