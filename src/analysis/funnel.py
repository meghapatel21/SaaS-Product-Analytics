"""Account-level funnels built only from states that exist in the data.

The dataset has no onboarding or activation events, and every account holds at least
one paid subscription, so a classic Signup -> Onboarding -> Activation -> Trial -> Paid
funnel is not observable. Two valid funnels are used instead (each stage requires all
previous stages):

Trial funnel:       Signed up -> Started a trial -> Converted to paid after trial -> Retained (churn_flag = FALSE)
Expansion funnel:   Signed up -> Paying -> Upgraded (any subscription upgrade_flag) -> Retained (churn_flag = FALSE)
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils.plotting import ACCENT, ACCENT_FILL, NEUTRAL, NEUTRAL_FILL, save_fig

FUNNELS = {
    "trial": [
        ("1. Signed up", lambda d: pd.Series(True, index=d.index)),
        ("2. Started a trial", lambda d: d["has_trial_subscription"]),
        ("3. Converted to paid after trial", lambda d: d["trial_converted"].fillna(False).astype(bool)),
        ("4. Retained (not churned)", lambda d: ~d["churn_flag"]),
    ],
    "expansion": [
        ("1. Signed up", lambda d: pd.Series(True, index=d.index)),
        ("2. Paying", lambda d: d["n_paid_subscriptions"] > 0),
        ("3. Upgraded", lambda d: d["any_upgrade"]),
        ("4. Retained (not churned)", lambda d: ~d["churn_flag"]),
    ],
}
SEGMENT_DIMENSIONS = ["plan_tier", "referral_source", "industry", "signup_quarter"]


def funnel_table(af: pd.DataFrame, funnel: str) -> pd.DataFrame:
    reached = pd.Series(True, index=af.index)
    rows = []
    for stage, cond in FUNNELS[funnel]:
        reached = reached & cond(af)
        rows.append({"funnel": funnel, "stage": stage, "accounts": int(reached.sum())})
    out = pd.DataFrame(rows)
    top = out["accounts"].iloc[0]
    out["conversion_from_signup"] = out["accounts"] / top
    out["step_conversion"] = out["accounts"] / out["accounts"].shift(1)
    out["step_drop_off"] = 1 - out["step_conversion"]
    return out


def funnel_by_segment(af: pd.DataFrame, funnel: str, dims=SEGMENT_DIMENSIONS) -> pd.DataFrame:
    frames = []
    for dim in dims:
        for value, grp in af.groupby(dim, observed=True):
            ft = funnel_table(grp, funnel)
            ft.insert(1, "dimension", dim)
            ft.insert(2, "segment", str(value))
            frames.append(ft)
    return pd.concat(frames, ignore_index=True)


def largest_bottleneck(ft: pd.DataFrame) -> pd.Series:
    return ft.dropna(subset=["step_drop_off"]).sort_values("step_drop_off", ascending=False).iloc[0]


def plot_funnels(tables: dict[str, pd.DataFrame]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, (name, ft) in zip(axes, tables.items()):
        y = np.arange(len(ft))[::-1]
        ax.barh(y, ft["accounts"], color=[ACCENT_FILL] + [NEUTRAL_FILL] * (len(ft) - 1),
                edgecolor=[ACCENT] + [NEUTRAL] * (len(ft) - 1), linewidth=0.6)
        for yi, (_, r) in zip(y, ft.iterrows()):
            step = "" if pd.isna(r["step_conversion"]) else f"  (step {r['step_conversion']:.1%})"
            ax.text(r["accounts"] + 5, yi, f"{r['accounts']:,}{step}", va="center", fontsize=9)
        ax.set_yticks(y, ft["stage"])
        ax.set_xlim(0, ft["accounts"].max() * 1.45)
        ax.set(title=f"{name.title()} funnel (accounts)", xlabel="Accounts")
        ax.grid(axis="y", visible=False)
    save_fig(fig, "02_funnels")


def plot_conversion_by_segment(seg: pd.DataFrame, stage: str, title: str, fname: str) -> None:
    d = seg[seg["stage"] == stage]
    dims = d["dimension"].unique()
    fig, axes = plt.subplots(1, len(dims), figsize=(4 * len(dims), 4), sharex=True)
    for ax, dim in zip(axes, dims):
        dd = d[d["dimension"] == dim].sort_values("step_conversion")
        ax.barh(dd["segment"], dd["step_conversion"], color=ACCENT_FILL, edgecolor=ACCENT, linewidth=0.6)
        ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
        ax.set(title=dim.replace("_", " ").title())
        for i, v in enumerate(dd["step_conversion"]):
            ax.text(v, i, f" {v:.0%}", va="center", fontsize=8)
    fig.suptitle(title, fontweight="bold")
    save_fig(fig, fname)
