"""Sample-size planning for a HYPOTHETICAL future A/B test (no experiment exists in the data).

Only the baseline rates and account inflow are real (computed from the dataset). The
minimum detectable effects are design choices, not results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

from src.utils.config import ALPHA


def power_table(baselines: dict[str, float], new_accounts_per_month: float, absolute_mdes=(0.02, 0.05, 0.10), power=0.8) -> pd.DataFrame:
    rows = []
    analysis = NormalIndPower()
    for metric, base in baselines.items():
        for mde in absolute_mdes:
            target = base - mde if "churn" in metric else base + mde
            if not 0 < target < 1:
                continue
            n = analysis.solve_power(effect_size=abs(proportion_effectsize(target, base)), alpha=ALPHA, power=power, ratio=1.0)
            rows.append({"metric": metric, "baseline_rate (observed)": base, "absolute_mde (design choice)": mde,
                         "target_rate": target, "accounts_per_arm": int(np.ceil(n)), "total_accounts": int(np.ceil(n)) * 2,
                         "months_of_new_accounts_needed": int(np.ceil(n)) * 2 / new_accounts_per_month})
    return pd.DataFrame(rows)
