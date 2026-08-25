"""Applies schema.sql. Plain CREATE TABLE IF NOT EXISTS, run every time —
no migrations framework/version table. This is a single-developer content
pipeline, not a multi-environment app backend: when the schema changes,
edit schema.sql directly and re-run `chckd-lists migrate`. If the change
is additive (new table/column), this just works. If it's a breaking change
to an existing column, drop data/chckd.duckdb and rebuild from the registry
+ sources — that's cheap here because this database is fully derived from
registry/ and the source APIs, not hand-entered data. Revisit this decision
if the db ever holds anything that can't be regenerated (see CLAUDE.md).
"""

import logging
from pathlib import Path

from chckd_lists.config import REPO_ROOT
from chckd_lists.db.connection import connect

logger = logging.getLogger(__name__)

SCHEMA_PATH = REPO_ROOT / "src" / "chckd_lists" / "db" / "schema.sql"


def migrate(db_path: Path | None = None) -> None:
    sql = SCHEMA_PATH.read_text()
    con = connect(db_path)
    try:
        con.execute(sql)
        logger.info("Schema applied from %s", SCHEMA_PATH)
    finally:
        con.close()


if __name__ == "__main__":
    from chckd_lists.logging_conf import setup_logging

    setup_logging()
    migrate()
