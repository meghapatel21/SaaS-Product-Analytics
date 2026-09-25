"""Reproducible cleaning pipeline: dataset/raw -> dataset/processed.

Principle: no record is deleted. Every anomaly becomes a boolean `dq_*` flag on the
row plus an entry in outputs/tables/data_quality_checks.csv, so analyses can decide
explicitly whether to include or exclude flagged rows.

Run:  python -m src.data.clean
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.config import PRICE_PER_SEAT, PROCESSED_DIR, RAW_DIR, SNAPSHOT_DATE, TABLES_DIR

DOMAINS = {
    "industry": {"DevTools", "FinTech", "Cybersecurity", "HealthTech", "EdTech"},
    "country": {"US", "UK", "IN", "AU", "DE", "CA", "FR"},
    "referral_source": {"organic", "ads", "event", "partner", "other"},
    "plan_tier": set(PRICE_PER_SEAT),
    "billing_frequency": {"monthly", "annual"},
    "priority": {"low", "medium", "high", "urgent"},
    "reason_code": {"pricing", "support", "features", "budget", "competitor", "unknown"},
}


class QualityLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, table: str, check: str, n: int, total: int, decision: str) -> None:
        self.rows.append({
            "table": table, "check": check, "n_affected": int(n), "n_rows": int(total),
            "pct_affected": round(100 * n / total, 2) if total else 0.0, "decision": decision,
        })

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def read_raw(name: str) -> pd.DataFrame:
    return pd.read_csv(RAW_DIR / f"ravenstack_{name}.csv")


def _strip(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            df[c] = df[c].str.strip()
    return df


def _parse_dates(df, cols, table, log):
    for c in cols:
        raw_null = df[c].isna()
        df[c] = pd.to_datetime(df[c], errors="coerce")
        log.add(table, f"unparseable {c}", (df[c].isna() & ~raw_null).sum(), len(df), "none found; would be set NULL and flagged")
        log.add(table, f"{c} after snapshot {SNAPSHOT_DATE.date()}", (df[c] > SNAPSHOT_DATE + pd.Timedelta(days=1)).sum(), len(df), "none found")
    return df


def _check_domains(df, table, log):
    for c, allowed in DOMAINS.items():
        if c in df.columns:
            bad = ~df[c].isin(allowed)
            log.add(table, f"{c} outside expected categories", bad.sum(), len(df), "none found; categories already consistent")


def _iqr_outliers(s: pd.Series) -> pd.Series:
    q1, q3 = s.quantile([0.25, 0.75])
    return s > q3 + 1.5 * (q3 - q1)


def clean_accounts(log: QualityLog) -> pd.DataFrame:
    t = "accounts"
    df = _strip(read_raw(t))
    df["referral_source"] = df["referral_source"].str.lower()
    log.add(t, "full-row duplicates", df.duplicated().sum(), len(df), "none found")
    log.add(t, "duplicate account_id", df["account_id"].duplicated().sum(), len(df), "none found; account_id is the primary key")
    df = _parse_dates(df, ["signup_date"], t, log)
    _check_domains(df, t, log)
    log.add(t, "seats <= 0", (df["seats"] <= 0).sum(), len(df), "none found")
    log.add(t, "seats IQR outliers", _iqr_outliers(df["seats"]).sum(), len(df),
            "kept: right-skewed seat counts are plausible for larger customers")
    df["signup_month"] = df["signup_date"].dt.to_period("M").dt.to_timestamp()
    df["tenure_days"] = (SNAPSHOT_DATE - df["signup_date"]).dt.days
    return df


def clean_subscriptions(log: QualityLog, accounts: pd.DataFrame) -> pd.DataFrame:
    t = "subscriptions"
    df = _strip(read_raw(t))
    log.add(t, "full-row duplicates", df.duplicated().sum(), len(df), "none found")
    log.add(t, "duplicate subscription_id", df["subscription_id"].duplicated().sum(), len(df), "none found")
    df = _parse_dates(df, ["start_date", "end_date"], t, log)
    _check_domains(df, t, log)

    df["dq_end_before_start"] = df["end_date"] < df["start_date"]
    log.add(t, "end_date < start_date", df["dq_end_before_start"].sum(), len(df), "none found")
    df["dq_zero_duration"] = df["end_date"] == df["start_date"]
    log.add(t, "end_date == start_date (0-day subscription)", df["dq_zero_duration"].sum(), len(df),
            "kept + flagged: same-day cancellation is a genuine business case")

    signup = df["account_id"].map(accounts.set_index("account_id")["signup_date"])
    df["dq_start_before_signup"] = df["start_date"] < signup
    log.add(t, "start_date < account signup_date", df["dq_start_before_signup"].sum(), len(df), "none found")

    df["dq_churn_flag_end_date_mismatch"] = df["churn_flag"] != df["end_date"].notna()
    log.add(t, "churn_flag inconsistent with end_date presence", df["dq_churn_flag_end_date_mismatch"].sum(), len(df),
            "none found: churn_flag = TRUE exactly when end_date is set")

    expected_mrr = np.where(df["is_trial"], 0, df["seats"] * df["plan_tier"].map(PRICE_PER_SEAT))
    df["dq_mrr_pricing_mismatch"] = df["mrr_amount"] != expected_mrr
    log.add(t, "mrr_amount != seats x list price (0 for trials)", df["dq_mrr_pricing_mismatch"].sum(), len(df),
            "none found: pricing is deterministic (Basic $19, Pro $49, Enterprise $199 per seat)")
    log.add(t, "arr_amount != 12 x mrr_amount", (df["arr_amount"] != 12 * df["mrr_amount"]).sum(), len(df), "none found")
    log.add(t, "negative mrr/arr/seats", ((df["mrr_amount"] < 0) | (df["seats"] <= 0)).sum(), len(df), "none found")

    df["dq_upgrade_and_downgrade"] = df["upgrade_flag"] & df["downgrade_flag"]
    log.add(t, "upgrade_flag AND downgrade_flag both TRUE", df["dq_upgrade_and_downgrade"].sum(), len(df),
            "kept + flagged: possible if plan moved both ways mid-cycle, but suspicious")
    log.add(t, "mrr_amount IQR outliers", _iqr_outliers(df["mrr_amount"]).sum(), len(df),
            "kept: explained by seats x Enterprise price, not errors")

    df["is_paid"] = ~df["is_trial"]
    df["start_month"] = df["start_date"].dt.to_period("M").dt.to_timestamp()
    df["is_active_at_snapshot"] = df["end_date"].isna()
    df["duration_days"] = (df["end_date"].fillna(SNAPSHOT_DATE) - df["start_date"]).dt.days
    return df


def clean_feature_usage(log: QualityLog, subs: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    t = "feature_usage"
    df = _strip(read_raw(t))
    log.add(t, "full-row duplicates", df.duplicated().sum(), len(df), "none found")

    df.insert(0, "usage_row_id", np.arange(1, len(df) + 1))
    df["dq_duplicate_usage_id"] = df["usage_id"].duplicated(keep=False)
    log.add(t, "usage_id shared by different records", df["dq_duplicate_usage_id"].sum(), len(df),
            "kept all rows (records differ in every attribute = ID collision, not duplication); "
            "added surrogate primary key usage_row_id")

    df["dq_same_sub_date_feature"] = df.duplicated(["subscription_id", "usage_date", "feature_name"], keep=False)
    log.add(t, "rows sharing subscription_id + usage_date + feature_name", df["dq_same_sub_date_feature"].sum(), len(df),
            "kept + flagged: multiple sessions of one feature on one day are plausible")

    df = _parse_dates(df, ["usage_date"], t, log)
    for c in ("usage_count", "usage_duration_secs", "error_count"):
        log.add(t, f"negative {c}", (df[c] < 0).sum(), len(df), "none found")
    df["dq_zero_usage"] = df["usage_count"] == 0
    log.add(t, "usage_count == 0", df["dq_zero_usage"].sum(), len(df), "kept + flagged (also have 0 duration: consistent empty session)")
    log.add(t, "usage_duration_secs IQR outliers", _iqr_outliers(df["usage_duration_secs"]).sum(), len(df), "kept: max 12,696 s (3.5 h) is plausible")

    s = subs.set_index("subscription_id")
    start = df["subscription_id"].map(s["start_date"])
    end = df["subscription_id"].map(s["end_date"])
    account_id = df["subscription_id"].map(s["account_id"])
    signup = account_id.map(accounts.set_index("account_id")["signup_date"])
    df["dq_before_subscription_start"] = df["usage_date"] < start
    df["dq_after_subscription_end"] = end.notna() & (df["usage_date"] > end)
    df["dq_before_account_signup"] = df["usage_date"] < signup
    df["is_in_subscription_window"] = ~(df["dq_before_subscription_start"] | df["dq_after_subscription_end"])
    log.add(t, "usage_date before its subscription start_date", df["dq_before_subscription_start"].sum(), len(df),
            "kept + flagged: systemic (generator did not align dates). Usage is used for lifetime behaviour, NOT lifecycle timing")
    log.add(t, "usage_date after its subscription end_date", df["dq_after_subscription_end"].sum(), len(df), "kept + flagged")
    log.add(t, "usage_date before account signup_date", df["dq_before_account_signup"].sum(), len(df),
            "kept + flagged: rules out activation / time-to-first-use analysis")

    beta_consistency = df.groupby("feature_name")["is_beta_feature"].nunique()
    log.add(t, "features whose is_beta_feature varies across rows", (beta_consistency > 1).sum(), beta_consistency.size,
            "kept: beta is treated as an attribute of the usage event (e.g. beta release of a feature), not of the feature")
    df["usage_month"] = df["usage_date"].dt.to_period("M").dt.to_timestamp()
    return df


def clean_support_tickets(log: QualityLog, accounts: pd.DataFrame) -> pd.DataFrame:
    t = "support_tickets"
    df = _strip(read_raw(t))
    df["priority"] = df["priority"].str.lower()
    log.add(t, "full-row duplicates", df.duplicated().sum(), len(df), "none found")
    log.add(t, "duplicate ticket_id", df["ticket_id"].duplicated().sum(), len(df), "none found")
    df = _parse_dates(df, ["submitted_at", "closed_at"], t, log)
    _check_domains(df, t, log)

    log.add(t, "closed_at < submitted_at", (df["closed_at"] < df["submitted_at"]).sum(), len(df), "none found")
    calc = (df["closed_at"] - df["submitted_at"]).dt.total_seconds() / 3600
    log.add(t, "resolution_time_hours != closed_at - submitted_at", (~np.isclose(calc, df["resolution_time_hours"])).sum(), len(df), "none found")

    df["dq_first_response_after_resolution"] = df["first_response_time_minutes"] > df["resolution_time_hours"] * 60
    log.add(t, "first_response_time_minutes > resolution time", df["dq_first_response_after_resolution"].sum(), len(df),
            "kept + flagged: logically impossible; excluded from first-response metrics")

    df["dq_satisfaction_out_of_range"] = df["satisfaction_score"].notna() & ~df["satisfaction_score"].between(1, 5)
    log.add(t, "satisfaction_score outside 1-5", df["dq_satisfaction_out_of_range"].sum(), len(df), "none found")
    df["has_satisfaction_response"] = df["satisfaction_score"].notna()
    log.add(t, "satisfaction_score NULL (no survey response)", (~df["has_satisfaction_response"]).sum(), len(df),
            "kept NULL (documented meaning: no response); never imputed. Note observed scores are only 3-5")
    df["satisfaction_score"] = df["satisfaction_score"].astype("Int64")

    signup = df["account_id"].map(accounts.set_index("account_id")["signup_date"])
    df["dq_before_account_signup"] = df["submitted_at"] < signup
    log.add(t, "ticket submitted before account signup_date", df["dq_before_account_signup"].sum(), len(df),
            "kept + flagged: systemic date misalignment; tickets used as lifetime support load only")
    df["submitted_month"] = df["submitted_at"].dt.to_period("M").dt.to_timestamp()
    return df


def clean_churn_events(log: QualityLog, accounts: pd.DataFrame) -> pd.DataFrame:
    t = "churn_events"
    df = _strip(read_raw(t))
    df["reason_code"] = df["reason_code"].str.lower()
    log.add(t, "full-row duplicates", df.duplicated().sum(), len(df), "none found")
    log.add(t, "duplicate churn_event_id", df["churn_event_id"].duplicated().sum(), len(df), "none found")
    df = _parse_dates(df, ["churn_date"], t, log)
    _check_domains(df, t, log)

    df = df.sort_values(["account_id", "churn_date", "churn_event_id"]).reset_index(drop=True)
    df["dq_duplicate_account_date"] = df.duplicated(["account_id", "churn_date"], keep="first")
    log.add(t, "second event for same account_id + churn_date", df["dq_duplicate_account_date"].sum(), len(df),
            "kept + flagged; excluded from event counts (one account cannot churn twice on one day)")

    signup = df["account_id"].map(accounts.set_index("account_id")["signup_date"])
    log.add(t, "churn_date < account signup_date", (df["churn_date"] < signup).sum(), len(df), "none found")
    log.add(t, "negative refund_amount_usd", (df["refund_amount_usd"] < 0).sum(), len(df), "none found")
    log.add(t, "feedback_text NULL", df["feedback_text"].isna().sum(), len(df), "kept NULL (optional comment)")
    log.add(t, "preceding_upgrade_flag AND preceding_downgrade_flag", (df["preceding_upgrade_flag"] & df["preceding_downgrade_flag"]).sum(), len(df),
            "kept: both can happen within a 90-day window")
    df["churn_month"] = df["churn_date"].dt.to_period("M").dt.to_timestamp()
    return df


def add_account_churn_reconciliation(accounts: pd.DataFrame, churn: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    valid = churn[~churn["dq_duplicate_account_date"]]
    agg = valid.groupby("account_id").agg(n_churn_events=("churn_event_id", "size"),
                                         first_churn_date=("churn_date", "min"),
                                         last_churn_date=("churn_date", "max"))
    accounts = accounts.merge(agg, on="account_id", how="left")
    accounts["n_churn_events"] = accounts["n_churn_events"].fillna(0).astype(int)
    accounts["has_churn_event"] = accounts["n_churn_events"] > 0
    accounts["dq_churn_flag_conflict"] = accounts["churn_flag"] != accounts["has_churn_event"]
    log.add("accounts", "churn_flag disagrees with presence of churn_events", accounts["dq_churn_flag_conflict"].sum(), len(accounts),
            "kept + flagged. Decision: churn_flag = account churn STATUS (primary churn label); "
            "churn_events = churn EPISODES (reasons, timing, reactivations)")
    return accounts


def run() -> dict[str, pd.DataFrame]:
    log = QualityLog()
    accounts = clean_accounts(log)
    subs = clean_subscriptions(log, accounts)
    usage = clean_feature_usage(log, subs, accounts)
    tickets = clean_support_tickets(log, accounts)
    churn = clean_churn_events(log, accounts)
    accounts = add_account_churn_reconciliation(accounts, churn, log)

    for sub_fk, parent, child, key in [
        ("subscriptions", accounts, subs, "account_id"),
        ("feature_usage", subs, usage, "subscription_id"),
        ("support_tickets", accounts, tickets, "account_id"),
        ("churn_events", accounts, churn, "account_id"),
    ]:
        log.add(sub_fk, f"orphan {key} (foreign key)", (~child[key].isin(parent[key])).sum(), len(child), "none found")

    tables = {"accounts": accounts, "subscriptions": subs, "feature_usage": usage,
              "support_tickets": tickets, "churn_events": churn}
    for name, df in tables.items():
        df.to_csv(PROCESSED_DIR / f"{name}.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    qlog = log.frame()
    qlog.to_csv(TABLES_DIR / "data_quality_checks.csv", index=False)
    return tables | {"quality_log": qlog}


if __name__ == "__main__":
    out = run()
    pd.set_option("display.width", 220, "display.max_colwidth", 70)
    print(out["quality_log"].query("n_affected > 0").to_string(index=False))
    for k, v in out.items():
        if k != "quality_log":
            print(f"{k:16s} {v.shape}")
