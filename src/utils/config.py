"""Project-wide paths and constants."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "dataset" / "raw"
PROCESSED_DIR = ROOT / "dataset" / "processed"
SQL_DIR = ROOT / "sql"
OUTPUTS_DIR = ROOT / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"
TABLES_DIR = OUTPUTS_DIR / "tables"
INSIGHTS_DIR = OUTPUTS_DIR / "insights"

for _d in (PROCESSED_DIR, FIGURES_DIR, TABLES_DIR, INSIGHTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Latest date observed in any table; all "as of" metrics and censoring use it.
SNAPSHOT_DATE = pd.Timestamp("2024-12-31")

# List price per seat per month, verified: every paid subscription has mrr = seats * price.
PRICE_PER_SEAT = {"Basic": 19, "Pro": 49, "Enterprise": 199}
PLAN_ORDER = ["Basic", "Pro", "Enterprise"]
PRIORITY_ORDER = ["low", "medium", "high", "urgent"]

ALPHA = 0.05
RANDOM_STATE = 42
