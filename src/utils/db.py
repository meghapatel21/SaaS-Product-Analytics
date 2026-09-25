"""PostgreSQL connection helper. Credentials come only from the environment / .env."""
import os

import psycopg

from src.utils.config import ROOT

REQUIRED = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")


def load_env(path=ROOT / ".env") -> None:
    """Minimal .env reader; variables already set in the environment win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_settings() -> None:
    load_env()
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing database settings: {missing}. Copy .env.example to .env and fill it in.")


def connect(dbname: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    require_settings()
    # libpq reads PGHOST/PGPORT/PGUSER/PGPASSWORD from the environment.
    return psycopg.connect(dbname=dbname or os.environ["PGDATABASE"], autocommit=autocommit)
