"""Analytical marts built from the processed tables.

`account_features` (one row per account) is the backbone for segmentation, churn
analysis, statistics and the churn model. Its SQL twin is analytics.account_features.

Behavioural and support measures are LIFETIME aggregates: usage and ticket dates are
not aligned with account signup/subscription dates, so no time-windowed behaviour
(e.g. "usage in first 30 days") is derived.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.segmentation import assign_segments
from src.utils.config import PLAN_ORDER, SNAPSHOT_DATE

TENURE_BINS = [-1, 180, 365, 540, np.inf]
TENURE_LABELS = ["0-6 months", "6-12 months", "12-18 months", "18-24 months"]


QUARTILE_LABELS = ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"]


def _quartile_band(s: pd.Series) -> pd.Categorical:
    """Band by P25/P50/P75 thresholds (ties stay together, so bands can be unequal in size).
    Deterministic and reproducible in SQL with PERCENTILE_CONT."""
    q1, q2, q3 = s.quantile([0.25, 0.50, 0.75])
    labels = np.select([s < q1, s < q2, s < q3], QUARTILE_LABELS[:3], default=QUARTILE_LABELS[3])
    return pd.Categorical(labels, QUARTILE_LABELS, ordered=True)


def _trial_conversion(subs: pd.DataFrame) -> pd.DataFrame:
    first_trial = subs[subs["is_trial"]].groupby("account_id")["start_date"].min().rename("first_trial_start")
    s = subs.join(first_trial, on="account_id")
    converted = (s["is_paid"] & (s["start_date"] >= s["first_trial_start"])).groupby(s["account_id"]).any()
    return pd.DataFrame({"first_trial_start": first_trial}).join(converted.rename("trial_converted"), how="outer")


def build_account_features(t: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, float]]:
    acc, subs, usage, tickets = t["accounts"], t["subscriptions"], t["feature_usage"], t["support_tickets"]

    af = acc[["account_id", "account_name", "industry", "country", "referral_source", "plan_tier", "seats",
              "is_trial", "churn_flag", "signup_date", "signup_month", "tenure_days",
              "n_churn_events", "has_churn_event", "first_churn_date"]].copy()
    af["signup_quarter"] = af["signup_date"].dt.to_period("Q").astype(str)
    af["tenure_bucket"] = pd.cut(af["tenure_days"], TENURE_BINS, labels=TENURE_LABELS)

    active = subs[subs["is_active_at_snapshot"]]
    s = subs.groupby("account_id").agg(
        n_subscriptions=("subscription_id", "size"),
        n_paid_subscriptions=("is_paid", "sum"),
        n_trial_subscriptions=("is_trial", "sum"),
        n_ended_subscriptions=("churn_flag", "sum"),
        n_upgrades=("upgrade_flag", "sum"),
        n_downgrades=("downgrade_flag", "sum"),
        annual_share=("billing_frequency", lambda x: (x == "annual").mean()),
        auto_renew_share=("auto_renew_flag", "mean"),
        lifetime_mrr_booked=("mrr_amount", "sum"),
    )
    s["has_trial_subscription"] = s["n_trial_subscriptions"] > 0
    s["any_upgrade"] = s["n_upgrades"] > 0
    s["any_downgrade"] = s["n_downgrades"] > 0
    s["highest_plan_tier"] = subs.assign(r=subs["plan_tier"].map({p: i for i, p in enumerate(PLAN_ORDER)})) \
        .groupby("account_id")["r"].max().map(dict(enumerate(PLAN_ORDER)))
    a = active.groupby("account_id").agg(n_active_subscriptions=("subscription_id", "size"),
                                        mrr_at_snapshot=("mrr_amount", "sum"))
    a["paid_seats_at_snapshot"] = active[active["is_paid"]].groupby("account_id")["seats"].sum()

    usage = usage.merge(subs[["subscription_id", "account_id"]], on="subscription_id")
    u = usage.groupby("account_id").agg(
        usage_events=("usage_row_id", "size"),
        total_usage_count=("usage_count", "sum"),
        distinct_features=("feature_name", "nunique"),
        total_duration_secs=("usage_duration_secs", "sum"),
        total_errors=("error_count", "sum"),
        beta_event_share=("is_beta_feature", "mean"),
    )
    u["total_duration_hours"] = u["total_duration_secs"] / 3600
    u["avg_minutes_per_event"] = u["total_duration_secs"] / u["usage_events"] / 60
    u["error_rate"] = u["total_errors"] / u["total_usage_count"]
    u = u.drop(columns="total_duration_secs")

    tk = tickets.assign(frt=tickets["first_response_time_minutes"].where(~tickets["dq_first_response_after_resolution"]),
                        urgent_high=tickets["priority"].isin(["high", "urgent"]))
    k = tk.groupby("account_id").agg(
        n_tickets=("ticket_id", "size"),
        n_escalations=("escalation_flag", "sum"),
        n_high_urgent_tickets=("urgent_high", "sum"),
        avg_resolution_hours=("resolution_time_hours", "mean"),
        avg_first_response_minutes=("frt", "mean"),
        csat_responses=("has_satisfaction_response", "sum"),
        avg_satisfaction=("satisfaction_score", "mean"),
    )

    af = af.merge(_trial_conversion(subs), left_on="account_id", right_index=True, how="left") \
        .merge(s, left_on="account_id", right_index=True, how="left") \
        .merge(a, left_on="account_id", right_index=True, how="left") \
        .merge(u, left_on="account_id", right_index=True, how="left") \
        .merge(k, left_on="account_id", right_index=True, how="left")

    zero_fill = ["n_active_subscriptions", "mrr_at_snapshot", "paid_seats_at_snapshot", "n_tickets",
                 "n_escalations", "n_high_urgent_tickets", "csat_responses"]
    af[zero_fill] = af[zero_fill].fillna(0)
    af["avg_satisfaction"] = af["avg_satisfaction"].astype(float)
    af["trial_converted"] = af["trial_converted"].astype("boolean").where(af["has_trial_subscription"])
    af["any_escalation"] = af["n_escalations"] > 0
    af["ticket_bucket"] = pd.cut(af["n_tickets"], [-1, 0, 2, 4, 6, np.inf], labels=["0", "1-2", "3-4", "5-6", "7+"])
    af["breadth_quartile"] = _quartile_band(af["distinct_features"])
    af["usage_quartile"] = _quartile_band(af["total_usage_count"])
    af["snapshot_date"] = SNAPSHOT_DATE
    return assign_segments(af)
