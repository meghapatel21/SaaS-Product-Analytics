"""Execute the SQL analysis scripts and export every named result set.

    python -m src.data.run_sql            # sql/02 ... sql/09
    python -m src.data.run_sql 05 07      # only files starting with these prefixes

Each result-returning statement must be preceded by a `-- name: <identifier>` comment;
results go to outputs/tables/sql/<file>__<name>.csv.
"""
import re
import sys

import pandas as pd

from src.utils.config import SQL_DIR, TABLES_DIR
from src.utils.db import connect

OUT_DIR = TABLES_DIR / "sql"
NAME_RE = re.compile(r"^--\s*name:\s*(\w+)", re.MULTILINE)


def run_file(conn, path) -> dict[str, pd.DataFrame]:
    text = path.read_text(encoding="utf-8")
    names = NAME_RE.findall(text)
    frames = []
    with conn.cursor() as cur:
        cur.execute(text)
        while True:
            if cur.description is not None:
                frames.append(pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description]))
            if not cur.nextset():
                break
    conn.commit()
    if len(names) != len(frames):
        raise RuntimeError(f"{path.name}: {len(names)} named queries but {len(frames)} result sets")
    results = dict(zip(names, frames))
    for name, df in results.items():
        df.to_csv(OUT_DIR / f"{path.stem}__{name}.csv", index=False)
    return results


def main(prefixes: list[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in SQL_DIR.glob("*.sql") if not p.name.startswith("01_"))
    if prefixes:
        files = [p for p in files if p.name.startswith(tuple(prefixes))]
    with connect() as conn:
        for path in files:
            results = run_file(conn, path)
            print(f"{path.name:32s} {len(results):>2} result sets: " + ", ".join(f"{k}({len(v)})" for k, v in results.items()))


if __name__ == "__main__":
    main(sys.argv[1:])
