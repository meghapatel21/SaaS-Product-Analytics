"""Load processed tables with correct dtypes."""
import pandas as pd

from src.utils.config import PROCESSED_DIR

DATE_COLS = {
    "accounts": ["signup_date", "signup_month", "first_churn_date", "last_churn_date"],
    "subscriptions": ["start_date", "end_date", "start_month"],
    "feature_usage": ["usage_date", "usage_month"],
    "support_tickets": ["submitted_at", "closed_at", "submitted_month"],
    "churn_events": ["churn_date", "churn_month"],
}


def load_table(name: str) -> pd.DataFrame:
    path = PROCESSED_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `python -m src.data.clean` first.")
    df = pd.read_csv(path, parse_dates=DATE_COLS[name])
    if "satisfaction_score" in df:
        df["satisfaction_score"] = df["satisfaction_score"].astype("Int64")
    return df


def load_all() -> dict[str, pd.DataFrame]:
    return {name: load_table(name) for name in DATE_COLS}
