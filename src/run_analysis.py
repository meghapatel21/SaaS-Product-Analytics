"""Run the complete Python analysis end to end.

    python -m src.data.clean      # raw -> processed
    python -m src.run_analysis    # processed -> outputs/{tables,figures,insights}
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.analysis import churn, feature_adoption as fa, funnel, kpis, marts, retention as ret, segmentation as seg
from src.statistics import churn_model, experiment_design, hypothesis_tests as ht
from src.utils.config import INSIGHTS_DIR, PLAN_ORDER, PROCESSED_DIR, TABLES_DIR
from src.utils.io import load_all
from src.utils.plotting import set_style

TABLEAU_DIR = TABLES_DIR / "tableau"
TABLEAU_DIR.mkdir(exist_ok=True)


def save(df: pd.DataFrame, name: str, index: bool = False, folder=TABLES_DIR) -> None:
    df.to_csv(folder / f"{name}.csv", index=index)


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else round(float(o), 6)
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    return str(o)


def main() -> dict:
    set_style()
    t = load_all()
    km: dict = {}

    # ---- Account mart + segmentation ----------------------------------------------------
    af, th = marts.build_account_features(t)
    af.to_csv(PROCESSED_DIR / "account_features.csv", index=False)
    save(af, "account_features", folder=TABLEAU_DIR)
    rules = seg.segment_rules_table(th); save(rules, "segment_rules")
    profile = seg.segment_profile(af); save(profile, "segment_profile")
    seg.plot_segments(profile, af["churn_flag"].mean())
    clusters = seg.clustering_check(af); save(clusters, "clustering_silhouette")
    km["segment_thresholds"] = th
    km["segment_profile"] = profile.to_dict(orient="records")
    km["clustering_best"] = clusters.sort_values("silhouette", ascending=False).iloc[0].to_dict()

    # ---- Feature adoption ----------------------------------------------------------------
    u = fa.usage_with_accounts(t, af)
    fs = fa.feature_summary(u, len(af)); save(fs, "feature_summary"); save(fs, "feature_summary", folder=TABLEAU_DIR)
    by_plan = fa.adoption_matrix(u, "subscription_plan_tier", PLAN_ORDER)
    save(by_plan, "feature_adoption_by_plan", index=True)
    # long form for Tableau: one row per feature x plan, so a heatmap needs no pivot
    save(by_plan.reset_index().melt(id_vars="feature_name", var_name="plan_tier", value_name="adoption_rate"),
         "feature_adoption_by_plan", folder=TABLEAU_DIR)
    by_industry = fa.adoption_matrix(u, "industry"); save(by_industry, "feature_adoption_by_industry", index=True)
    by_segment = fa.adoption_matrix(u, "engagement_segment", seg.SEGMENT_ORDER); save(by_segment, "feature_adoption_by_engagement_segment", index=True)
    plan_prof = fa.plan_usage_profile(u, t["subscriptions"]); save(plan_prof, "plan_usage_profile")
    beta = fa.beta_comparison(u); save(beta, "beta_vs_ga_usage")
    mu = fa.monthly_usage(u); save(mu, "monthly_usage"); save(mu, "usage_monthly_overall", folder=TABLEAU_DIR)
    feat_month = u.groupby(["usage_month", "feature_name"]).agg(
        usage_events=("usage_row_id", "size"), accounts=("account_id", "nunique"), usage_count=("usage_count", "sum"),
        errors=("error_count", "sum"), beta_events=("is_beta_feature", "sum")).reset_index()
    save(feat_month, "feature_usage_monthly", folder=TABLEAU_DIR)
    fa.plot_feature_adoption(fs)
    fa.plot_adoption_heatmap(by_plan, "Feature adoption within plan tier\n(share of accounts with usage on that tier)", "10_feature_adoption_by_plan")
    fa.plot_monthly_usage(mu)
    km["features"] = {
        "top5": fs.head(5)[["feature_name", "adoption_rate", "adopting_accounts"]].to_dict(orient="records"),
        "bottom5": fs.tail(5)[["feature_name", "adoption_rate", "adopting_accounts"]].to_dict(orient="records"),
        "adoption_rate_min": fs["adoption_rate"].min(), "adoption_rate_max": fs["adoption_rate"].max(),
        "adoption_rate_mean": fs["adoption_rate"].mean(),
        "underutilized": fs.loc[fs["adoption_quadrant"].str.startswith("Underutilized"), "feature_name"].tolist(),
        "errors_per_100_uses_max": fs.sort_values("errors_per_100_uses").iloc[-1][["feature_name", "errors_per_100_uses"]].to_dict(),
        "errors_per_100_uses_min": fs.sort_values("errors_per_100_uses").iloc[0][["feature_name", "errors_per_100_uses"]].to_dict(),
        "plan_profile": plan_prof.to_dict(orient="records"), "beta_vs_ga": beta.to_dict(orient="records"),
        "monthly_accounts_with_usage_min": int(mu["accounts_with_usage"].min()), "monthly_accounts_with_usage_max": int(mu["accounts_with_usage"].max()),
    }

    # ---- KPIs ----------------------------------------------------------------------------
    monthly = kpis.monthly_metrics(t); save(monthly, "monthly_kpis"); save(monthly, "monthly_kpis", folder=TABLEAU_DIR)
    head = kpis.headline_kpis(t, af, monthly, fs); save(head, "headline_kpis")
    kpis.plot_monthly(monthly)
    km["headline_kpis"] = dict(zip(head["metric"], head["value"]))
    y24 = monthly[monthly["month"].dt.year == 2024]
    km["mrr_2023_12"] = int(monthly.loc[monthly["month"] == "2023-12-01", "mrr"].iloc[0])
    km["monthly_churn_2024_range"] = [y24["subscription_churn_rate"].min(), y24["subscription_churn_rate"].max()]

    # ---- Funnels -------------------------------------------------------------------------
    funnels = {name: funnel.funnel_table(af, name) for name in funnel.FUNNELS}
    seg_funnels = {name: funnel.funnel_by_segment(af, name) for name in funnel.FUNNELS}
    all_f = pd.concat(funnels.values()); save(all_f, "funnel_overall"); save(all_f, "funnel_overall", folder=TABLEAU_DIR)
    tk = t["support_tickets"]
    support = tk.groupby("priority").agg(
        tickets=("ticket_id", "size"), avg_resolution_hours=("resolution_time_hours", "mean"),
        median_first_response_minutes=("first_response_time_minutes", lambda x: x[~tk.loc[x.index, "dq_first_response_after_resolution"]].median()),
        escalation_rate=("escalation_flag", "mean"), csat_response_rate=("has_satisfaction_response", "mean"),
        avg_csat=("satisfaction_score", "mean")).reindex(["low", "medium", "high", "urgent"]).reset_index()
    save(support, "support_by_priority")
    km["support_by_priority"] = support.to_dict(orient="records")
    all_seg = pd.concat(seg_funnels.values()); save(all_seg, "funnel_by_segment"); save(all_seg, "funnel_by_segment", folder=TABLEAU_DIR)
    funnel.plot_funnels(funnels)
    funnel.plot_conversion_by_segment(seg_funnels["trial"], "3. Converted to paid after trial", "Trial-to-paid step conversion by segment", "03a_trial_conversion_by_segment")
    funnel.plot_conversion_by_segment(seg_funnels["trial"], "4. Retained (not churned)", "Retention step (converted -> not churned) by segment", "03b_funnel_retention_step_by_segment")
    km["funnels"] = {k: v.to_dict(orient="records") for k, v in funnels.items()}
    km["funnel_bottleneck"] = {k: funnel.largest_bottleneck(v)[["stage", "step_drop_off"]].to_dict() for k, v in funnels.items()}
    conv = seg_funnels["trial"][seg_funnels["trial"]["stage"] == "3. Converted to paid after trial"]
    km["trial_conversion_by_segment_range"] = {d: {"min": g.nsmallest(1, "step_conversion")[["segment", "step_conversion", "accounts"]].to_dict(orient="records")[0],
                                                   "max": g.nlargest(1, "step_conversion")[["segment", "step_conversion", "accounts"]].to_dict(orient="records")[0]}
                                               for d, g in conv.groupby("dimension")}

    # ---- Retention -----------------------------------------------------------------------
    s = ret.subscription_frame(t, af)
    a = ret.account_frame(af)
    sub_ret = pd.concat([ret.subscription_window_retention(s).assign(dimension="overall")] +
                        [ret.subscription_window_retention(s, d) for d in ("plan_tier", "billing_frequency", "referral_source", "is_trial", "breadth_quartile", "engagement_segment", "start_quarter")])
    save(sub_ret, "subscription_retention_windows"); save(sub_ret, "subscription_retention_windows", folder=TABLEAU_DIR)
    acc_ret = pd.concat([ret.account_window_retention(a).assign(dimension="overall")] +
                        [ret.account_window_retention(a, d) for d in ("signup_quarter", "referral_source", "plan_tier", "breadth_quartile", "engagement_segment")])
    save(acc_ret, "account_retention_windows"); save(acc_ret, "account_retention_windows", folder=TABLEAU_DIR)
    cm = ret.monthly_cohort_matrix(s); save(cm, "subscription_cohort_matrix", index=True)
    cm_long = cm.drop(columns="cohort_size").reset_index().melt(id_vars="cohort", var_name="months_since_start", value_name="retention_rate").dropna()
    cm_long = cm_long.merge(cm["cohort_size"].reset_index(), on="cohort")
    save(cm_long, "subscription_cohort_retention_long", folder=TABLEAU_DIR)
    km_plan = ret.kaplan_meier(s, "duration_days", "churn_flag", list(range(0, 366, 5)), "plan_tier"); save(km_plan, "km_subscription_by_plan")
    km_all = ret.kaplan_meier(s, "duration_days", "churn_flag", ret.SUB_WINDOWS); save(km_all, "km_subscription_overall")
    km_acc = ret.kaplan_meier(a, "duration", "event", ret.ACCOUNT_WINDOWS); save(km_acc, "km_account_overall")
    acc_q = acc_ret[acc_ret["dimension"] == "signup_quarter"]
    ret.plot_cohort_heatmap(cm)
    ret.plot_retention_curves(km_plan, acc_q)
    quarter_q = ret.quarterly_cohort_retention(s); save(quarter_q, "subscription_retention_by_start_quarter", index=True)
    km["retention"] = {
        "subscription_overall": sub_ret[sub_ret["dimension"] == "overall"][["window_days", "eligible", "retention_rate"]].to_dict(orient="records"),
        "subscription_km_overall": km_all.to_dict(orient="records"),
        "subscription_d90_by": sub_ret[sub_ret["window_days"] == 90][["dimension", "group", "eligible", "retention_rate"]].to_dict(orient="records"),
        "account_overall": acc_ret[acc_ret["dimension"] == "overall"][["window_days", "eligible", "retention_rate"]].to_dict(orient="records"),
        "account_km_overall": km_acc.to_dict(orient="records"),
        "account_by_dim_d90_d180": acc_ret[acc_ret["window_days"].isin([90, 180]) & (acc_ret["dimension"] != "overall")][["dimension", "group", "window_days", "eligible", "retention_rate"]].to_dict(orient="records"),
        "quarterly_subscription_cohorts": quarter_q.reset_index().to_dict(orient="records"),
        "cohort_m3_worst": {f"{k:%Y-%m}": v for k, v in cm[3].dropna().nsmallest(3).items()},
        "cohort_m3_best": {f"{k:%Y-%m}": v for k, v in cm[3].dropna().nlargest(3).items()},
    }

    # ---- Churn ---------------------------------------------------------------------------
    drivers, dim_tests = churn.churn_by_dimension(af)
    save(drivers, "churn_by_segment"); save(drivers, "churn_by_segment", folder=TABLEAU_DIR); save(dim_tests, "churn_dimension_tests")
    numeric = churn.numeric_comparison(af); save(numeric, "churn_numeric_comparison")
    reasons = churn.churn_reasons(t, af)
    save(reasons["reasons"], "churn_reasons"); save(reasons["reasons_by_plan"], "churn_reasons_by_plan", index=True)
    save(reasons["reason_vs_feedback"], "churn_reason_vs_feedback", index=True); save(reasons["events_by_quarter"], "churn_events_by_quarter", index=True)
    ce = t["churn_events"][~t["churn_events"]["dq_duplicate_account_date"]].merge(
        af[["account_id", "plan_tier", "industry", "referral_source", "engagement_segment", "churn_flag"]].rename(columns={"churn_flag": "account_churn_flag"}), on="account_id")
    save(ce, "churn_events_enriched", folder=TABLEAU_DIR)
    overall = af["churn_flag"].mean()
    churn.plot_churn_drivers(drivers, dim_tests, overall, ["plan_tier", "referral_source", "industry", "engagement_segment", "breadth_quartile", "tenure_bucket", "any_escalation"])
    churn.plot_churn_reasons(reasons["reasons"], reasons["events_by_quarter"])
    km["churn"] = {"overall_account_churn_rate": overall, "dimension_tests": dim_tests.to_dict(orient="records"),
                   "numeric_top": numeric.head(6).to_dict(orient="records"), "reasons": reasons["reasons"].to_dict(orient="records")}

    # ---- Statistics ----------------------------------------------------------------------
    tests = ht.run_tests(af, t["subscriptions"], t["feature_usage"], a, t["support_tickets"])
    save(tests, "statistical_tests")
    (INSIGHTS_DIR / "statistical_tests.md").write_text(ht.to_markdown(tests), encoding="utf-8")
    km["tests"] = tests[["test_id", "statistic_name", "statistic", "p_value", "p_holm", "reject_h0", "effect_size_name", "effect_size", "observed", "ci"]].to_dict(orient="records")

    model = churn_model.run(af)
    save(model["metrics"], "churn_model_metrics"); save(model["coefficients"], "churn_model_lr_coefficients"); save(model["permutation_importance"], "churn_model_rf_permutation_importance")
    km["model"] = {"metrics": model["metrics"].to_dict(orient="records"), "n_train": model["n_train"], "n_test": model["n_test"],
                   "top_permutation": model["permutation_importance"].head(5).to_dict(orient="records")}

    acc_d90 = acc_ret[(acc_ret["dimension"] == "overall") & (acc_ret["window_days"] == 90)]["retention_rate"].iloc[0]
    new_per_month = (af["signup_date"].dt.year == 2024).sum() / 12
    power = experiment_design.power_table({"account churn rate (churn_flag)": overall,
                                           "churn event within 90 days of signup": 1 - acc_d90}, new_per_month)
    save(power, "experiment_power_hypothetical")
    km["experiment_power"] = {"new_accounts_per_month_2024": new_per_month, "table": power.to_dict(orient="records")}

    (INSIGHTS_DIR / "key_metrics.json").write_text(json.dumps(km, indent=2, default=_jsonable), encoding="utf-8")
    return km


if __name__ == "__main__":
    main()
    print("Analysis complete: outputs/tables, outputs/figures, outputs/insights")
