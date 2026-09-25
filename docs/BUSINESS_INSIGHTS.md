# Business Insights

Every number below comes from `outputs/tables/`, `outputs/insights/key_metrics.json` or `sql/09_business_insights.sql`, as of 2024-12-31.
**All findings are observational associations. None is a causal effect, and no A/B test exists in the data.**
Holm-adjusted p-values refer to the 11-test family in `outputs/insights/statistical_tests.md`.
The dataset is synthetic, so insight 8 (instrumentation) matters as much as the behavioural findings.

---

## 1. Trial conversion is not the problem; keeping converted customers is

| | |
|---|---|
| **Finding** | Almost every trial converts, but about a quarter of converted accounts are flagged as churned. The retention step is the largest drop-off in the trial funnel. |
| **Evidence** | 403 accounts trialled → 380 converted to paid (**94.3%**) → 291 not churned (**76.6%** step conversion; **23.4%** drop-off vs 5.7% at trial-to-paid). Trial conversion varies little by segment: 91.9% (partner) to 96.4% (organic); 93.0% (Pro) to 96.7% (Enterprise). |
| **Why it matters** | Spending on conversion optimisation targets a stage that already performs. The revenue leak comes after the sale. |
| **Recommended action** | Move growth effort from trial conversion to post-conversion onboarding and customer success. Validate with the randomised onboarding test in `docs/EXPERIMENT_DESIGN.md`. |
| **Business impact** | Targets the stage that loses 89 converted accounts. Any gain must be measured experimentally; this analysis cannot size a causal effect. |

## 2. Event- and ads-sourced customers churn more than partner and organic customers (directional)

| | |
|---|---|
| **Finding** | Churn differs by acquisition channel, most visibly after trial conversion, though the difference is not statistically significant after correction. |
| **Evidence** | Account churn: partner **14.6%** (95% CI 8.7–23.4%), organic **17.5%**, ads 23.5%, other 24.3%, event **30.2%** (21.9–40.0%). Converted-trial accounts that stay: partner and organic **83.8%** vs event **62.9%**. Chi-square p = 0.079 raw, **0.79 Holm-adjusted**; Cramér's V = 0.13. Event accounts hold 16.3% of snapshot MRR. |
| **Why it matters** | If real, channel mix determines how much acquired revenue is kept, not just how much is acquired. |
| **Recommended action** | Do **not** reallocate budget on this evidence alone. Report churn by channel monthly, add retention-weighted CAC to channel reviews, and re-test once more accounts accumulate. |
| **Business impact** | Low-cost monitoring now; possible spend reallocation later if the gap persists. |

## 3. DevTools customers show the highest churn (directional)

| | |
|---|---|
| **Finding** | DevTools has roughly twice the churn of Cybersecurity and EdTech. |
| **Evidence** | DevTools **31.0%** (CI 23.2–40.0%, n = 113) vs Cybersecurity **16.0%** (n = 100), EdTech 16.5%, FinTech 22.3%, HealthTech 21.9%. Chi-square p = 0.066 raw, **0.72 Holm-adjusted**. DevTools holds 21.3% of snapshot MRR. |
| **Why it matters** | DevTools is the largest segment by account count. A true gap would be a material retention risk. |
| **Recommended action** | Run qualitative churn interviews with DevTools accounts. Recorded reason codes cannot explain the gap (see insight 8). Treat it as a hypothesis to validate, not a targeting rule. |
| **Business impact** | Could focus research on the segment with the most accounts at risk, at low cost. |

## 4. Usage volume and feature breadth do not identify churn risk

| | |
|---|---|
| **Finding** | More engaged or broader-adopting accounts do **not** churn less. The observed difference points slightly the other way and is not significant. Behavioural data does not separate churners. |
| **Evidence** | High engagement (Power + Engaged) **25.2%** churn vs low **18.8%** (difference 6.4 pp, 95% CI −0.9 to 13.6 pp, Holm p = 0.79). Broad adopters (≥ 28 features) 24.3% vs narrow 18.9% (CI −2.0 to 12.5 pp). Median lifetime usage: churned 528 vs retained 491 (Mann-Whitney p = 0.21). Churn models: cross-validated ROC-AUC **0.52** (logistic regression) and **0.53** (random forest) vs **0.50** baseline. |
| **Why it matters** | A customer health score built on usage volume would not flag at-risk accounts here and would waste customer-success time. |
| **Recommended action** | Do not launch a usage-based health score yet. First instrument lifecycle-aligned signals: usage trend after signup, seat utilisation, onboarding milestones. Then re-evaluate. |
| **Business impact** | Avoids building a scoring system that performs near chance. |

## 5. Enterprise is three-quarters of revenue and churns at the same rate as other plans

| | |
|---|---|
| **Finding** | Revenue is concentrated in Enterprise, and plan tier is not associated with churn. Each Enterprise loss therefore costs far more. |
| **Evidence** | Enterprise = **74.3%** of snapshot MRR ($7.55M of $10.16M) from 34.4% of active subscriptions; Basic = 6.8% of MRR. Account churn: Basic 22.0%, Pro 21.9%, Enterprise 22.1% (chi-square p = 0.999). Subscription survival does not differ by plan (log-rank p = 0.77). |
| **Why it matters** | Equal churn rates across plans mean retention effort should follow revenue at risk, not account counts. |
| **Recommended action** | Prioritise named account management and renewal reviews for Enterprise. Measure retention KPIs in MRR terms (gross MRR churn) alongside logo churn. |
| **Business impact** | Directs retention capacity at about three-quarters of recurring revenue. |

## 6. Feature adoption is uniform: no breakout feature and no dead feature

| | |
|---|---|
| **Finding** | All 40 features have similar reach, intensity and error rates across plans. Beta releases are as reliable as GA. |
| **Evidence** | Account adoption ranges from **65.4%** (feature_18) to **74.8%** (feature_12). The largest within-plan adoption gap for any feature is 9 pp. Errors per 100 uses: 4.71 to 6.56 by feature. Beta vs GA errors per event: 0.557 vs 0.565 (Mann-Whitney p = 0.74). 12 features fall in the "narrow but intensive" quadrant (below-median reach, above-median use per adopter). |
| **Why it matters** | No single feature explains retention or plan value. Packaging features by plan is not reflected in usage. |
| **Recommended action** | Test discoverability (in-app prompts) for the 12 narrow-but-intensive features. Review whether plan packaging differentiates value, since usage is the same on Basic and Enterprise. Continue the beta programme; no quality gap is visible. |
| **Business impact** | Low-risk adoption gains on features that users value once found; input to pricing and packaging. |

## 7. Support does not prioritise urgent tickets, and CSAT captures no dissatisfaction

| | |
|---|---|
| **Finding** | Resolution time is the same for every priority, and satisfaction data covers only neutral-to-positive answers. |
| **Evidence** | Mean resolution: urgent **34.6 h**, high 37.0 h, medium 35.6 h, low 36.3 h (medians 33 / 38 / 34 / 36 h). Kruskal-Wallis H = 3.41, **p = 0.33**, ε² = 0.002: no evidence that priority changes resolution time. Escalation rate about 5% at every priority. CSAT response rate **58.75%**; only scores 3, 4 and 5 occur (average 3.98). Accounts with an escalation churn 25.3% vs 21.3% (odds ratio 1.25, 95% CI 0.74–2.12, not significant). |
| **Why it matters** | Urgent issues wait as long as low-priority ones, and the survey cannot detect unhappy customers. |
| **Recommended action** | Introduce priority-based SLAs (e.g. an urgent first-response target) and track SLA attainment. Redesign the CSAT survey so low scores can be captured, and raise the response rate. |
| **Business impact** | Faster handling for the tickets most likely to block customers, and a usable early-warning signal. |

## 8. Churn and product instrumentation must be fixed before retention programmes can be managed

| | |
|---|---|
| **Finding** | Core lifecycle data is internally inconsistent. |
| **Evidence** | `churn_flag` contradicts `churn_events` for **312 of 500 accounts (62.4%)**. All 110 churn-flagged accounts still hold active paid subscriptions (**$2.07M MRR, 20.4%** of total). **52.8%** of usage events and **53.9%** of tickets are dated before the account's signup. `upgrade_flag` does not track tier changes. Churn `reason_code` and `feedback_text` do not agree. |
| **Why it matters** | Churn rate, MRR, activation and health scores all depend on these fields. Today they can give conflicting answers to "how many customers did we lose?" |
| **Recommended action** | Define one churn event of record, tied to subscription cancellation and billing end. Enforce event timestamps at ingestion (usage ≥ signup). Add automated checks like `sql/02_data_quality.sql` to the pipeline. |
| **Business impact** | Prerequisite for credible board-level churn and MRR reporting and for any experiment. |

## 9. Churn events are accelerating faster than the customer base

| | |
|---|---|
| **Finding** | Churn events per customer rose sharply through 2024. |
| **Evidence** | Churn events per 100 signed-up accounts: **10.9** (2023Q1), 16.3 (2023Q4), 26.4 (2024Q2), 31.0 (2024Q3), **50.0** (2024Q4). Monthly subscription churn (start-of-month base) ranged 0.73%–2.40% in 2024. Newer signup cohorts reach their first churn event sooner (D90 without a churn event: 81.8% for 2023Q1 vs 41.7% for 2024Q3). This cohort gap is **confounded** by the calendar concentration of events and is not evidence that newer customers are worse. |
| **Why it matters** | If the trend is real, it will erode the MRR growth seen in 2024. Subscription starts also surged (2,069 in 2024Q4), which may reflect data generation rather than business reality. |
| **Recommended action** | Track churn intensity (events per active account) monthly as a leading KPI. Confirm with billing-system data before reacting (see insight 8). |
| **Business impact** | Early warning on the largest threat to recurring revenue. |

---

## Recommendations summary (prioritised)

1. **Fix churn and event instrumentation** (insight 8). Every other programme depends on it.
2. **Shift growth focus to post-conversion retention**, validated by a randomised onboarding test (insights 1, 9).
3. **Protect Enterprise revenue** with account management and MRR-based retention KPIs (insight 5).
4. **Introduce priority SLAs and a redesigned CSAT** (insight 7).
5. **Monitor channel and industry churn gaps** before changing acquisition spend or targeting (insights 2, 3).
6. **Run discoverability tests** for narrow-but-intensive features; review plan packaging (insight 6).
7. **Hold off on usage-based health scores** until lifecycle-aligned signals exist (insight 4).
