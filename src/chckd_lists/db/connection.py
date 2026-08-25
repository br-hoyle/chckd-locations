from pathlib import Path

import duckdb

from chckd_lists.config import DATA_DIR, DB_PATH


def connect(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))
