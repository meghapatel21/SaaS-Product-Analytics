"""Rule-based engagement segmentation of accounts (+ a clustering sanity check).

The dataset has no individual-user table, so the segmented entity is the ACCOUNT.
Usage dates are not aligned with account lifecycles (see DATA_QUALITY_REPORT), so
recency-based segments ("Dormant", "At-Risk") are not supported; segments use
lifetime usage volume and breadth only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src.utils.config import RANDOM_STATE

SEGMENT_ORDER = ["Power Accounts", "Engaged Accounts", "Casual Accounts", "Low-Engagement Accounts"]


def segment_thresholds(af: pd.DataFrame) -> dict[str, float]:
    return {
        "usage_p25": float(af["total_usage_count"].quantile(0.25)),
        "usage_p50": float(af["total_usage_count"].quantile(0.50)),
        "usage_p75": float(af["total_usage_count"].quantile(0.75)),
        "breadth_p75": float(af["distinct_features"].quantile(0.75)),
        "error_rate_p75": float(af["error_rate"].quantile(0.75)),
    }


def assign_segments(af: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    th = segment_thresholds(af)
    u, b = af["total_usage_count"], af["distinct_features"]
    af = af.copy()
    af["engagement_segment"] = np.select(
        [(u >= th["usage_p75"]) & (b >= th["breadth_p75"]), u >= th["usage_p50"], u >= th["usage_p25"]],
        SEGMENT_ORDER[:3], default=SEGMENT_ORDER[3])
    af["engagement_segment"] = pd.Categorical(af["engagement_segment"], SEGMENT_ORDER, ordered=True)
    # Friction overlay (independent of engagement): error-prone usage or an escalated ticket.
    af["high_friction"] = (af["error_rate"] >= th["error_rate_p75"]) | af["any_escalation"]
    return af, th


def segment_rules_table(th: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([
        ("Power Accounts", f"total_usage_count >= {th['usage_p75']:.0f} (P75) AND distinct_features >= {th['breadth_p75']:.0f} (P75)"),
        ("Engaged Accounts", f"not Power AND total_usage_count >= {th['usage_p50']:.0f} (P50)"),
        ("Casual Accounts", f"{th['usage_p25']:.0f} (P25) <= total_usage_count < {th['usage_p50']:.0f} (P50)"),
        ("Low-Engagement Accounts", f"total_usage_count < {th['usage_p25']:.0f} (P25)"),
        ("high_friction (overlay)", f"error_rate >= {th['error_rate_p75']:.4f} (P75) OR any escalated ticket"),
    ], columns=["segment", "rule"])


def segment_profile(af: pd.DataFrame) -> pd.DataFrame:
    g = af.groupby("engagement_segment", observed=True)
    out = g.agg(
        accounts=("account_id", "size"),
        median_usage_count=("total_usage_count", "median"),
        median_distinct_features=("distinct_features", "median"),
        median_duration_hours=("total_duration_hours", "median"),
        mean_error_rate=("error_rate", "mean"),
        mean_tickets=("n_tickets", "mean"),
        high_friction_share=("high_friction", "mean"),
        mrr_at_snapshot=("mrr_at_snapshot", "sum"),
        churn_rate=("churn_flag", "mean"),
    )
    out["share_of_accounts"] = out["accounts"] / out["accounts"].sum()
    return out.reset_index()


def plot_segments(profile: pd.DataFrame, overall_churn: float) -> None:
    import matplotlib.pyplot as plt

    from src.utils.plotting import ACCENT, ACCENT_FILL, NEUTRAL, NEUTRAL_FILL, save_fig

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    labels = profile["engagement_segment"].astype(str).str.replace(" Accounts", "")
    axes[0].bar(labels, profile["share_of_accounts"], color=NEUTRAL_FILL, edgecolor=NEUTRAL, linewidth=0.6)
    axes[0].set(title="Share of accounts")
    axes[1].bar(labels, profile["median_distinct_features"], color=NEUTRAL_FILL, edgecolor=NEUTRAL, linewidth=0.6)
    axes[1].set(title="Median distinct features used (of 40)")
    axes[2].bar(labels, profile["churn_rate"], color=ACCENT_FILL, edgecolor=ACCENT, linewidth=0.6)
    axes[2].axhline(overall_churn, color="black", lw=0.8, ls="--")
    axes[2].set(title="Account churn rate (dashed = overall)")
    for ax, pct in zip(axes, (True, False, True)):
        ax.tick_params(axis="x", rotation=20)
        if pct:
            ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    save_fig(fig, "11_engagement_segments")


CLUSTER_FEATURES =["total_usage_count", "distinct_features", "total_duration_hours", "error_rate", "n_tickets", "seats"]


def clustering_check(af: pd.DataFrame, k_range=range(2, 7)) -> pd.DataFrame:
    """K-means silhouette scan on standardized behavioural features.

    Used only to decide whether clustering adds value over the rule-based segments.
    """
    X = StandardScaler().fit_transform(af[CLUSTER_FEATURES])
    rows = []
    for k in k_range:
        labels = KMeans(n_clusters=k, n_init=20, random_state=RANDOM_STATE).fit_predict(X)
        rows.append({"k": k, "silhouette": silhouette_score(X, labels),
                     "smallest_cluster_share": np.bincount(labels).min() / len(labels)})
    return pd.DataFrame(rows)
