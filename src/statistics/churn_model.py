"""Small supporting churn model (secondary to the product analytics).

Question: can account-level behavioural / commercial features distinguish accounts with
churn_flag = TRUE? Prediction is not causation: a predictive feature is not a lever.

Leakage guard: features derived from churn_events, ended subscriptions or the snapshot
state (active subscriptions, MRR at snapshot) are excluded.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import RepeatedStratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.utils.config import RANDOM_STATE
from src.utils.plotting import ACCENT, NEUTRAL, NEUTRAL_FILL, save_fig

NUMERIC = ["seats", "tenure_days", "n_subscriptions", "n_trial_subscriptions", "n_upgrades", "n_downgrades",
           "annual_share", "auto_renew_share", "total_usage_count", "distinct_features", "total_duration_hours",
           "avg_minutes_per_event", "error_rate", "beta_event_share", "n_tickets", "n_escalations",
           "n_high_urgent_tickets", "avg_resolution_hours", "avg_first_response_minutes", "csat_responses", "avg_satisfaction"]
CATEGORICAL = ["plan_tier", "industry", "country", "referral_source", "is_trial"]


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), CATEGORICAL),
    ])


def models() -> dict[str, Pipeline]:
    return {
        "Baseline (stratified dummy)": Pipeline([("prep", _preprocessor()), ("clf", DummyClassifier(strategy="stratified", random_state=RANDOM_STATE))]),
        "Logistic Regression": Pipeline([("prep", _preprocessor()), ("clf", LogisticRegression(class_weight="balanced", max_iter=5000, C=0.5))]),
        "Random Forest": Pipeline([("prep", _preprocessor()), ("clf", RandomForestClassifier(
            n_estimators=500, min_samples_leaf=5, class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1))]),
    }


def run(af: pd.DataFrame) -> dict:
    X = af[NUMERIC + CATEGORICAL].copy()
    X["is_trial"] = X["is_trial"].astype(str)
    y = af["churn_flag"].astype(int)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=RANDOM_STATE)
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=RANDOM_STATE)
    rng = np.random.default_rng(RANDOM_STATE)

    metrics, rocs, fitted = [], {}, {}
    for name, pipe in models().items():
        cv_auc = cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc")
        pipe.fit(X_tr, y_tr)
        proba = pipe.predict_proba(X_te)[:, 1]
        pred = (proba >= 0.5).astype(int)
        boot = []
        for _ in range(2000):
            idx = rng.integers(0, len(y_te), len(y_te))
            if y_te.iloc[idx].nunique() == 2:
                boot.append(roc_auc_score(y_te.iloc[idx], proba[idx]))
        tn, fp, fn, tp = confusion_matrix(y_te, pred, labels=[0, 1]).ravel()
        metrics.append({"model": name, "cv_roc_auc_mean": cv_auc.mean(), "cv_roc_auc_std": cv_auc.std(),
                        "test_roc_auc": roc_auc_score(y_te, proba), "test_auc_ci_low": np.percentile(boot, 2.5),
                        "test_auc_ci_high": np.percentile(boot, 97.5),
                        "precision": precision_score(y_te, pred, zero_division=0), "recall": recall_score(y_te, pred, zero_division=0),
                        "f1": f1_score(y_te, pred, zero_division=0), "tn": tn, "fp": fp, "fn": fn, "tp": tp})
        rocs[name] = roc_curve(y_te, proba)
        fitted[name] = pipe

    lr = fitted["Logistic Regression"]
    names = lr.named_steps["prep"].get_feature_names_out()
    coefs = pd.DataFrame({"feature": names, "coefficient": lr.named_steps["clf"].coef_[0]})
    coefs["odds_ratio_per_unit"] = np.exp(coefs["coefficient"])
    coefs = coefs.reindex(coefs["coefficient"].abs().sort_values(ascending=False).index)

    rf = fitted["Random Forest"]
    pi = permutation_importance(rf, X_te, y_te, scoring="roc_auc", n_repeats=30, random_state=RANDOM_STATE, n_jobs=-1)
    perm = pd.DataFrame({"feature": X.columns, "importance_mean": pi.importances_mean, "importance_std": pi.importances_std}) \
        .sort_values("importance_mean", ascending=False)

    _plot(rocs, metrics, perm)
    return {"metrics": pd.DataFrame(metrics), "coefficients": coefs, "permutation_importance": perm,
            "n_train": len(y_tr), "n_test": len(y_te), "test_churn_rate": y_te.mean()}


def _plot(rocs, metrics, perm) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    styles = {"Baseline (stratified dummy)": (NEUTRAL, ":"), "Logistic Regression": (ACCENT, "-"), "Random Forest": ("#2E7FA0", "--")}
    auc = {m["model"]: m["test_roc_auc"] for m in metrics}
    for name, (fpr, tpr, _) in rocs.items():
        c, ls = styles[name]
        axes[0].plot(fpr, tpr, color=c, ls=ls, lw=2, label=f"{name} (AUC {auc[name]:.2f})")
    axes[0].plot([0, 1], [0, 1], color="grey", lw=0.8)
    axes[0].set(title="ROC curves on held-out test set (n=125)", xlabel="False positive rate", ylabel="True positive rate")
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    top = perm.head(12).iloc[::-1]
    axes[1].barh(top["feature"], top["importance_mean"], xerr=top["importance_std"], color=NEUTRAL_FILL, edgecolor=NEUTRAL, linewidth=0.6, ecolor=NEUTRAL)
    axes[1].axvline(0, color="black", lw=0.8)
    axes[1].set(title="Random Forest permutation importance\n(drop in test ROC-AUC; bars crossing 0 = no signal)", xlabel="Mean AUC decrease")
    save_fig(fig, "12_churn_model")
