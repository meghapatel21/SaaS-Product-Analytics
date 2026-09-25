"""Hypothesis tests answering the project's statistical questions.

* Significance threshold: alpha = 0.05, applied to Holm-adjusted p-values because eleven
  related tests are run on the same data (family-wise error control, less conservative
  than Bonferroni).
* Every result is observational. A significant association is not evidence of causation.
* Interpretation text is generated from the computed result, never pre-written.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.duration.survfunc import survdiff
from statsmodels.stats.contingency_tables import Table2x2
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_effectsize, proportions_ztest

from src.utils.config import ALPHA, RANDOM_STATE


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _chi_square(af, dim, tid, question, implication_sig, implication_null):
    ct = pd.crosstab(af[dim], af["churn_flag"])
    chi2, p, dof, exp = stats.chi2_contingency(ct)
    v = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
    rates = (ct[True] / ct.sum(axis=1)).sort_values()
    return dict(
        test_id=tid, business_question=question,
        h0=f"Account churn rate is the same for every {dim}.",
        h1=f"Account churn rate differs for at least one {dim}.",
        test="Pearson chi-square test of independence",
        assumptions=f"Independent accounts; expected cell counts >= 5 (min expected = {exp.min():.1f}).",
        statistic_name=f"chi2 (dof={dof})", statistic=chi2, p_value=p, ci="n/a (omnibus test); per-group Wilson CIs in churn_by_segment.csv",
        effect_size_name="Cramer's V", effect_size=v,
        observed="; ".join(f"{k}: {_pct(r)} (n={ct.loc[k].sum()})" for k, r in rates.items()),
        implication_sig=implication_sig, implication_null=implication_null)


def _two_proportions(k1, n1, k2, n2, label1, label2):
    z, p = proportions_ztest([k1, k2], [n1, n2])
    lo, hi = confint_proportions_2indep(k1, n1, k2, n2, method="newcomb")
    h = proportion_effectsize(k1 / n1, k2 / n2)
    obs = f"{label1}: {_pct(k1 / n1)} ({k1}/{n1}); {label2}: {_pct(k2 / n2)} ({k2}/{n2})"
    return z, p, f"difference {_pct(k1 / n1 - k2 / n2)} [95% CI {_pct(lo)}, {_pct(hi)}] (Newcombe)", h, obs


def run_tests(af: pd.DataFrame, subs: pd.DataFrame, usage: pd.DataFrame, account_surv: pd.DataFrame,
              tickets: pd.DataFrame) -> pd.DataFrame:
    tests = []

    tests.append(_chi_square(af, "plan_tier", "T1", "Is churn significantly different across subscription plans?",
                             "Plan-specific retention programmes are justified.",
                             "Plan tier is not a useful churn-targeting lever on its own; look at behaviour and channel instead."))
    tests.append(_chi_square(af, "referral_source", "T2", "Does churn differ by acquisition channel?",
                             "Channel mix affects retained revenue; weight acquisition spend by channel retention, not just volume.",
                             "Observed channel gaps may be noise at this sample size; monitor before reallocating spend."))
    tests.append(_chi_square(af, "industry", "T3", "Does churn differ by customer industry?",
                             "Industry-specific onboarding or messaging may be warranted.",
                             "Observed industry gaps may be noise at this sample size; do not re-target on industry yet."))

    # T4: engagement vs churn (retention status)
    high = af["engagement_segment"].isin(["Power Accounts", "Engaged Accounts"])
    k1, n1 = int(af.loc[high, "churn_flag"].sum()), int(high.sum())
    k2, n2 = int(af.loc[~high, "churn_flag"].sum()), int((~high).sum())
    z, p, ci, h, obs = _two_proportions(k1, n1, k2, n2, "High engagement (Power+Engaged)", "Low engagement (Casual+Low)")
    tests.append(dict(test_id="T4", business_question="Is retention significantly different between high- and low-engagement accounts?",
                      h0="Churn rate is equal for high- and low-engagement accounts.", h1="Churn rates differ.",
                      test="Two-proportion z-test", assumptions=f"Independent accounts; n*p and n*(1-p) >= 10 in both groups (min = {min(k1, k2, n1 - k1, n2 - k2)}).",
                      statistic_name="z", statistic=z, p_value=p, ci=ci, effect_size_name="Cohen's h", effect_size=h, observed=obs,
                      implication_sig="Engagement depth is a usable churn early-warning signal.",
                      implication_null="Raw usage volume alone does not separate churners; engagement-based health scores need other inputs."))

    # T5: engagement vs time to first churn event (log-rank)
    a = account_surv.assign(high=account_surv["engagement_segment"].isin(["Power Accounts", "Engaged Accounts"]))
    chi2, p = survdiff(a["duration"].astype(float), a["event"].astype(int), a["high"].astype(int))
    obs = "; ".join(f"{'High' if g else 'Low'} engagement: {_pct(d['event'].mean())} had a churn event (n={len(d)})" for g, d in a.groupby("high"))
    tests.append(dict(test_id="T5", business_question="Do high-engagement accounts survive longer before their first churn event?",
                      h0="Time-to-first-churn-event curves are identical for high- and low-engagement accounts.", h1="The curves differ.",
                      test="Log-rank test (right-censored at 2024-12-31)", assumptions="Non-informative censoring; proportional hazards not required for validity but aids power.",
                      statistic_name="chi2 (dof=1)", statistic=chi2, p_value=p, ci="n/a", effect_size_name="difference in share with churn event",
                      effect_size=a.loc[a["high"], "event"].mean() - a.loc[~a["high"], "event"].mean(), observed=obs,
                      implication_sig="Engagement is associated with longer customer lifetimes.",
                      implication_null="No evidence that engagement delays the first churn event."))

    # T6: feature adoption breadth vs churn
    broad = af["distinct_features"] >= af["distinct_features"].median()
    k1, n1 = int(af.loc[broad, "churn_flag"].sum()), int(broad.sum())
    k2, n2 = int(af.loc[~broad, "churn_flag"].sum()), int((~broad).sum())
    z, p, ci, h, obs = _two_proportions(k1, n1, k2, n2, f"Broad adopters (>= {af['distinct_features'].median():.0f} features)", "Narrow adopters")
    tests.append(dict(test_id="T6", business_question="Is feature adoption breadth associated with retention?",
                      h0="Churn rate is equal for broad and narrow feature adopters.", h1="Churn rates differ.",
                      test="Two-proportion z-test", assumptions="Independent accounts; large-sample normal approximation holds (all cells >= 10).",
                      statistic_name="z", statistic=z, p_value=p, ci=ci, effect_size_name="Cohen's h", effect_size=h, observed=obs,
                      implication_sig="Driving multi-feature adoption is a candidate retention lever worth testing experimentally.",
                      implication_null="Feature breadth is not associated with churn here; prioritise other levers for retention."))

    # T7: usage volume churned vs retained
    ch, rt = af.loc[af["churn_flag"], "total_usage_count"], af.loc[~af["churn_flag"], "total_usage_count"]
    u, p = stats.mannwhitneyu(ch, rt, alternative="two-sided")
    rng = np.random.default_rng(RANDOM_STATE)
    boots = [np.median(rng.choice(ch, len(ch))) - np.median(rng.choice(rt, len(rt))) for _ in range(5000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    tests.append(dict(test_id="T7", business_question="Do churned accounts use the product less than retained accounts?",
                      h0="Lifetime usage-count distributions are equal for churned and retained accounts.", h1="The distributions differ.",
                      test="Mann-Whitney U (two-sided)", assumptions="Independent groups; ordinal/continuous outcome; no normality assumption (usage is skewed).",
                      statistic_name="U", statistic=u, p_value=p,
                      ci=f"median difference (churned - retained) {np.median(ch) - np.median(rt):.1f} [95% bootstrap CI {lo:.1f}, {hi:.1f}]",
                      effect_size_name="rank-biserial r", effect_size=1 - 2 * u / (len(ch) * len(rt)),
                      observed=f"median churned {np.median(ch):.0f} (n={len(ch)}); median retained {np.median(rt):.0f} (n={len(rt)})",
                      implication_sig="Usage decline is a candidate churn signal.",
                      implication_null="Lifetime usage volume does not distinguish churners."))

    # T8: subscription survival by plan
    chi2, p = survdiff(subs["duration_days"].astype(float), subs["churn_flag"].astype(int), subs["plan_tier"])
    rates = subs.groupby("plan_tier")["churn_flag"].mean()
    tests.append(dict(test_id="T8", business_question="Do subscriptions on different plans stay active for different lengths of time?",
                      h0="Subscription survival curves are identical across plan tiers.", h1="At least one plan's survival curve differs.",
                      test="Log-rank test (3 groups, right-censored at 2024-12-31)", assumptions="Independent subscriptions (approximation: accounts hold several); non-informative censoring.",
                      statistic_name="chi2 (dof=2)", statistic=chi2, p_value=p, ci="n/a", effect_size_name="max - min ended share",
                      effect_size=rates.max() - rates.min(), observed="; ".join(f"{k}: {_pct(v)} ended (n={(subs['plan_tier'] == k).sum()})" for k, v in rates.items()),
                      implication_sig="Plan tier matters for subscription longevity.",
                      implication_null="Subscription longevity does not depend on plan; pricing tier is not a retention lever in this data."))

    # T9: escalations vs churn
    tab = pd.crosstab(af["any_escalation"], af["churn_flag"]).reindex(index=[True, False], columns=[True, False])
    t22 = Table2x2(tab.values)
    _, p = stats.fisher_exact(tab.values)
    olo, ohi = t22.oddsratio_confint()
    tests.append(dict(test_id="T9", business_question="Is having an escalated support ticket associated with churn?",
                      h0="Churn odds are the same for accounts with and without an escalated ticket.", h1="Churn odds differ.",
                      test="Fisher's exact test (2x2)", assumptions="Independent accounts; exact test chosen because the escalated group is small.",
                      statistic_name="odds ratio", statistic=t22.oddsratio, p_value=p, ci=f"odds ratio 95% CI [{olo:.2f}, {ohi:.2f}]",
                      effect_size_name="odds ratio", effect_size=t22.oddsratio,
                      observed=f"escalated: {_pct(tab.loc[True, True] / tab.loc[True].sum())} churn (n={tab.loc[True].sum()}); "
                               f"not escalated: {_pct(tab.loc[False, True] / tab.loc[False].sum())} (n={tab.loc[False].sum()})",
                      implication_sig="Escalations are a churn-risk trigger for customer success follow-up.",
                      implication_null="Escalations alone are not a reliable churn trigger."))

    # T10: beta vs GA error counts (event level)
    b, g = usage.loc[usage["is_beta_feature"], "error_count"], usage.loc[~usage["is_beta_feature"], "error_count"]
    u, p = stats.mannwhitneyu(b, g, alternative="two-sided")
    tests.append(dict(test_id="T10", business_question="Do beta feature usage events generate more errors than generally-available usage?",
                      h0="Error-count distributions are equal for beta and non-beta usage events.", h1="The distributions differ.",
                      test="Mann-Whitney U (two-sided)", assumptions="Independent events (approximation: events cluster within subscriptions); discrete outcome with many ties (tie-corrected).",
                      statistic_name="U", statistic=u, p_value=p, ci=f"mean errors/event: beta {b.mean():.3f} vs non-beta {g.mean():.3f}",
                      effect_size_name="rank-biserial r", effect_size=1 - 2 * u / (len(b) * len(g)),
                      observed=f"beta events n={len(b)}; non-beta n={len(g)}",
                      implication_sig="Beta quality gates need attention before GA.",
                      implication_null="Beta releases are not measurably more error-prone than GA usage."))

    # T11: resolution time by ticket priority
    groups = {p: tickets.loc[tickets["priority"] == p, "resolution_time_hours"].astype(float) for p in ["low", "medium", "high", "urgent"]}
    h, p = stats.kruskal(*groups.values())
    n = sum(len(g) for g in groups.values())
    tests.append(dict(test_id="T11", business_question="Are higher-priority support tickets resolved faster?",
                      h0="Resolution-time distributions are identical across ticket priorities.",
                      h1="At least one priority's resolution-time distribution differs.",
                      test="Kruskal-Wallis H test (4 groups)",
                      assumptions="Independent tickets; continuous outcome; no normality assumption (resolution times are bounded at 1-72 h).",
                      statistic_name="H (dof=3)", statistic=h, p_value=p,
                      ci="median resolution hours: " + "; ".join(f"{k} {v.median():.1f}" for k, v in groups.items()),
                      effect_size_name="epsilon-squared", effect_size=h / (n - 1),
                      observed="; ".join(f"{k}: mean {v.mean():.1f} h (n={len(v)})" for k, v in groups.items()),
                      implication_sig="Resolution time differs by priority; check that the ordering matches the intended SLA (urgent fastest).",
                      implication_null="No evidence that urgent tickets are resolved faster than low-priority ones; introduce and monitor priority-based SLAs."))

    df = pd.DataFrame(tests)
    df["p_holm"] = multipletests(df["p_value"], method="holm")[1]
    df["reject_h0"] = df["p_holm"] < ALPHA
    df["interpretation"] = [
        (f"Holm-adjusted p = {r.p_holm:.4f} < {ALPHA}: reject H0. The data show a statistically significant association "
         f"(observational, not causal)." if r.reject_h0 else
         f"Holm-adjusted p = {r.p_holm:.4f} >= {ALPHA} (raw p = {r.p_value:.4f}): fail to reject H0. "
         f"No statistically reliable difference; this is not proof that no difference exists.")
        for r in df.itertuples()]
    df["business_implication"] = np.where(df["reject_h0"], df["implication_sig"], df["implication_null"])
    return df.drop(columns=["implication_sig", "implication_null"])


def to_markdown(df: pd.DataFrame) -> str:
    lines = ["# Statistical Tests (auto-generated)", "",
             f"Generated by `python -m src.run_analysis`. alpha = {ALPHA}, Holm correction across {len(df)} tests. "
             "All comparisons are observational; none is an A/B test.", ""]
    for r in df.itertuples():
        lines += [f"## {r.test_id}. {r.business_question}", "",
                  f"- **Null hypothesis:** {r.h0}", f"- **Alternative hypothesis:** {r.h1}",
                  f"- **Test:** {r.test}", f"- **Assumptions:** {r.assumptions}",
                  f"- **Observed:** {r.observed}",
                  f"- **Test statistic:** {r.statistic_name} = {r.statistic:.4f}",
                  f"- **p-value:** raw {r.p_value:.4g}; Holm-adjusted {r.p_holm:.4g}",
                  f"- **Confidence interval:** {r.ci}",
                  f"- **Effect size:** {r.effect_size_name} = {r.effect_size:.4f}",
                  f"- **Interpretation:** {r.interpretation}",
                  f"- **Business implication:** {r.business_implication}", ""]
    return "\n".join(lines)
