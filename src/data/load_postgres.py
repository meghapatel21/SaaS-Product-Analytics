"""Create the database, build the schema and bulk-load the processed CSVs.

    python -m src.data.load_postgres

Credentials: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE from the environment or .env.
"""
import os

from psycopg import sql

from src.utils.config import PROCESSED_DIR, SQL_DIR
from src.utils.db import connect, require_settings

TABLES = ["accounts", "subscriptions", "feature_usage", "support_tickets", "churn_events"]  # parent -> child order


def ensure_database() -> None:
    require_settings()
    name = os.environ["PGDATABASE"]
    with connect("postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print(f"created database {name}")


def load() -> dict[str, int]:
    ensure_database()
    counts = {}
    with connect() as conn:
        conn.execute((SQL_DIR / "01_schema.sql").read_text(encoding="utf-8"))
        for table in TABLES:
            path = PROCESSED_DIR / f"{table}.csv"
            with path.open(encoding="utf-8") as f:
                header = f.readline().strip().split(",")
            copy_stmt = sql.SQL("COPY core.{} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, header)))
            with conn.cursor() as cur, cur.copy(copy_stmt) as copy, path.open("rb") as f:
                while chunk := f.read(1 << 16):
                    copy.write(chunk)
            counts[table] = conn.execute(sql.SQL("SELECT COUNT(*) FROM core.{}").format(sql.Identifier(table))).fetchone()[0]
            print(f"core.{table:16s} {counts[table]:>6,} rows")
        conn.execute("ANALYZE")
    return counts


if __name__ == "__main__":
    load()
