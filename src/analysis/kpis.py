"""SaaS / product KPIs that the dataset can actually support.

Conventions (mirrored in sql/03_product_kpis.sql):
* A subscription is ACTIVE at date d when start_date <= d AND (end_date IS NULL OR end_date > d).
  end_date is treated as the day the subscription stopped, so it is no longer active on it.
* MRR at d = SUM(mrr_amount) of subscriptions active at d. Accounts can hold several
  concurrent subscriptions (line items); their MRR is summed.
* Monthly churn rates use the base active at the END of the previous month, so
  subscriptions that start and end inside the same month do not inflate the rate.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from src.utils.config import SNAPSHOT_DATE
from src.utils.plotting import ACCENT, ACCENT_FILL, ALERT, ALERT_FILL, NEUTRAL, save_fig


def _active_mask(subs: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    return (subs["start_date"] <= d) & (subs["end_date"].isna() | (subs["end_date"] > d))


def monthly_metrics(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    acc, subs, usage, tickets, churn = (t[k] for k in ("accounts", "subscriptions", "feature_usage", "support_tickets", "churn_events"))
    churn = churn[~churn["dq_duplicate_account_date"]]
    usage = usage.merge(subs[["subscription_id", "account_id"]], on="subscription_id")
    month_ends = pd.date_range("2023-01-31", SNAPSHOT_DATE, freq="ME")
    rows, prev_end = [], None
    for me in month_ends:
        ms = me.to_period("M").to_timestamp()
        active = subs[_active_mask(subs, me)]
        paid = active[active["is_paid"]]
        ended_in_month = subs["end_date"].between(ms, me)
        if prev_end is not None:
            base = subs[_active_mask(subs, prev_end)]
            ended_from_base = base[base["end_date"].between(ms, me)]
            base_n, base_mrr = len(base), base["mrr_amount"].sum()
        else:
            ended_from_base, base_n, base_mrr = subs.iloc[0:0], 0, 0
        in_month_usage = usage[usage["usage_month"] == ms]
        rows.append({
            "month": ms,
            "new_accounts": int((acc["signup_month"] == ms).sum()),
            "cumulative_accounts": int((acc["signup_date"] <= me).sum()),
            "new_subscriptions": int((subs["start_month"] == ms).sum()),
            "new_subscription_mrr": int(subs.loc[subs["start_month"] == ms, "mrr_amount"].sum()),
            "active_subscriptions": len(active),
            "paying_accounts": paid["account_id"].nunique(),
            "paid_seats": int(paid["seats"].sum()),
            "mrr": int(active["mrr_amount"].sum()),
            "ended_subscriptions": int(ended_in_month.sum()),
            "ended_subscriptions_from_base": len(ended_from_base),
            "churned_mrr_from_base": int(ended_from_base["mrr_amount"].sum()),
            "start_of_month_subscriptions": base_n,
            "start_of_month_mrr": int(base_mrr),
            "churn_events": int((churn["churn_month"] == ms).sum()),
            "accounts_with_churn_event": churn.loc[churn["churn_month"] == ms, "account_id"].nunique(),
            "usage_events": len(in_month_usage),
            "accounts_with_usage": in_month_usage["account_id"].nunique(),
            "support_tickets": int((tickets["submitted_month"] == ms).sum()),
        })
        prev_end = me
    m = pd.DataFrame(rows)
    m["arr"] = m["mrr"] * 12
    m["arpa"] = m["mrr"] / m["paying_accounts"]
    m["revenue_per_paid_seat"] = m["mrr"] / m["paid_seats"]
    m["subscription_churn_rate"] = m["ended_subscriptions_from_base"] / m["start_of_month_subscriptions"]
    m["gross_mrr_churn_rate"] = m["churned_mrr_from_base"] / m["start_of_month_mrr"]
    return m


def headline_kpis(t: dict[str, pd.DataFrame], af: pd.DataFrame, monthly: pd.DataFrame, feature_summary: pd.DataFrame) -> pd.DataFrame:
    subs, tickets, churn = t["subscriptions"], t["support_tickets"], t["churn_events"]
    churn_v = churn[~churn["dq_duplicate_account_date"]]
    active = subs[subs["is_active_at_snapshot"]]
    paid_active = active[active["is_paid"]]
    y2024 = monthly[monthly["month"].dt.year == 2024]
    trial_accounts = af["has_trial_subscription"].sum()
    frt = tickets.loc[~tickets["dq_first_response_after_resolution"], "first_response_time_minutes"]

    k = [
        ("Accounts", "Total accounts", len(af), "COUNT(DISTINCT account_id)"),
        ("Accounts", "New accounts 2023", int((af["signup_date"].dt.year == 2023).sum()), "accounts with signup_date in 2023"),
        ("Accounts", "New accounts 2024", int((af["signup_date"].dt.year == 2024).sum()), "accounts with signup_date in 2024"),
        ("Revenue", "Active subscriptions at snapshot", len(active), "subscriptions with end_date IS NULL"),
        ("Revenue", "MRR at snapshot ($)", int(active["mrr_amount"].sum()), "SUM(mrr_amount) of active subscriptions"),
        ("Revenue", "ARR at snapshot ($)", int(active["arr_amount"].sum()), "SUM(arr_amount) of active subscriptions = 12 x MRR"),
        ("Revenue", "ARPA ($/month)", active["mrr_amount"].sum() / paid_active["account_id"].nunique(), "MRR / paying accounts"),
        ("Revenue", "Revenue per paid seat ($/month)", active["mrr_amount"].sum() / paid_active["seats"].sum(), "MRR / SUM(seats) of active paid subscriptions"),
        ("Conversion", "Accounts that ever started a trial", int(trial_accounts), "accounts with >=1 is_trial subscription"),
        ("Conversion", "Trial-to-paid conversion rate", af["trial_converted"].sum() / trial_accounts, "trial accounts with a paid subscription starting on/after first trial start / trial accounts"),
        ("Churn", "Account churn rate (churn_flag)", af["churn_flag"].mean(), "accounts with churn_flag = TRUE / total accounts"),
        ("Churn", "Logo retention rate (1 - account churn)", 1 - af["churn_flag"].mean(), "accounts with churn_flag = FALSE / total accounts"),
        ("Churn", "Accounts with >=1 churn event", af["has_churn_event"].mean(), "accounts in churn_events / total accounts (includes reactivated accounts)"),
        ("Churn", "Reactivation share of churn events", churn_v["is_reactivation"].mean(), "churn events with is_reactivation = TRUE / churn events"),
        ("Churn", "Lifetime subscription churn rate", subs["churn_flag"].mean(), "subscriptions with an end_date / all subscriptions"),
        ("Churn", "Avg monthly subscription churn rate 2024", y2024["subscription_churn_rate"].mean(), "mean over 2024 of (ended from start-of-month base / start-of-month base)"),
        ("Churn", "Avg monthly gross MRR churn rate 2024", y2024["gross_mrr_churn_rate"].mean(), "mean over 2024 of (MRR ended from base / start-of-month MRR)"),
        ("Expansion", "Subscription upgrade rate", subs["upgrade_flag"].mean(), "subscriptions with upgrade_flag / all subscriptions"),
        ("Expansion", "Subscription downgrade rate", subs["downgrade_flag"].mean(), "subscriptions with downgrade_flag / all subscriptions"),
        ("Engagement", "Mean feature adoption rate (40 features)", feature_summary["adoption_rate"].mean(), "mean over features of (accounts using feature / total accounts)"),
        ("Engagement", "Median distinct features per account", af["distinct_features"].median(), "median of COUNT(DISTINCT feature_name) per account"),
        ("Support", "Tickets per account", len(tickets) / len(af), "tickets / total accounts"),
        ("Support", "Escalation rate", tickets["escalation_flag"].mean(), "escalated tickets / tickets"),
        ("Support", "CSAT response rate", tickets["has_satisfaction_response"].mean(), "tickets with satisfaction_score / tickets"),
        ("Support", "Average CSAT (1-5, responders)", tickets["satisfaction_score"].mean(), "AVG(satisfaction_score) where not NULL"),
        ("Support", "Median resolution time (hours)", tickets["resolution_time_hours"].median(), "median resolution_time_hours"),
        ("Support", "Median first response (minutes)", frt.median(), "median first_response_time_minutes, excluding 36 impossible records"),
    ]
    return pd.DataFrame(k, columns=["area", "metric", "value", "formula"])


def plot_monthly(monthly: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    m = monthly
    axes[0, 0].plot(m["month"], m["mrr"] / 1e6, color=ALERT, lw=2)
    axes[0, 0].fill_between(m["month"], m["mrr"] / 1e6, color=ALERT_FILL)
    axes[0, 0].set(title="MRR at month end", ylabel="MRR ($M)")
    axes[0, 1].bar(m["month"], m["new_accounts"], width=20, color=ACCENT_FILL, edgecolor=ACCENT, linewidth=0.6)
    axes[0, 1].set(title="New accounts per month", ylabel="Accounts")
    axes[1, 0].plot(m["month"], m["subscription_churn_rate"], color=ACCENT, lw=2, label="Subscriptions")
    axes[1, 0].plot(m["month"], m["gross_mrr_churn_rate"], color=NEUTRAL, lw=2, ls="--", label="MRR")
    axes[1, 0].yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0, decimals=1))
    axes[1, 0].set(title="Monthly churn rate (start-of-month base)", ylabel="Churn rate")
    axes[1, 0].legend(frameon=False)
    axes[1, 1].plot(m["month"], m["arpa"], color=ACCENT, lw=2)
    axes[1, 1].set(title="ARPA (MRR per paying account)", ylabel="$ / month")
    for ax in axes.flat:
        ax.tick_params(axis="x", rotation=45)
    save_fig(fig, "01_monthly_kpis")
