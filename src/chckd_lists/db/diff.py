"""Per-run change logging (CLAUDE.md "Change logging").

Usage, per table touched during a pipeline run:

    with TableDiff(con, run_id, "places") as d:
        ... upsert into places ...
    # on exit, d has already logged a row to table_change_log and emitted
    # a log line like "places: +3 -0 ~1 (61 -> 64)"

The diff is computed with plain SQL (row count before/after, and EXCEPT for
added/removed rows) rather than a generic ORM-style diff library — DuckDB is
an analytical engine, so let it do the set arithmetic.
"""

import logging

import duckdb

from chckd_lists.ids import make_id

logger = logging.getLogger(__name__)


class TableDiff:
    def __init__(self, con: duckdb.DuckDBPyConnection, run_id: str, table_name: str):
        self.con = con
        self.run_id = run_id
        self.table_name = table_name
        self._before_rows: set[tuple] = set()
        self.rows_before = 0

    def __enter__(self) -> "TableDiff":
        self._before_rows = self._snapshot()
        self.rows_before = len(self._before_rows)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            return  # don't log a diff for a failed run
        after_rows = self._snapshot()
        rows_after = len(after_rows)
        added = len(after_rows - self._before_rows)
        removed = len(self._before_rows - after_rows)
        # "updated" isn't derivable from row-set difference alone (a row that
        # changed looks like one remove + one add). We report it as 0 here;
        # tables that need real update-detection should diff on a natural key
        # instead of the whole row — not needed yet for this pipeline's
        # append-mostly tables.
        updated = 0

        self.con.execute(
            """
            INSERT INTO table_change_log
                (id, run_id, table_name, rows_before, rows_after, rows_added, rows_removed, rows_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                make_id("table_change_log", f"{self.run_id}:{self.table_name}"),
                self.run_id,
                self.table_name,
                self.rows_before,
                rows_after,
                added,
                removed,
                updated,
            ],
        )

        if added or removed:
            logger.info(
                "%s: +%d -%d (%d -> %d)", self.table_name, added, removed, self.rows_before, rows_after
            )
        else:
            logger.info("%s: no change (%d rows)", self.table_name, rows_after)

    def _snapshot(self) -> set[tuple]:
        # updated_at ticks forward on every upsert of an unchanged row, which
        # would make every re-run look like a full remove+add of every row.
        # Excluding it means the diff reflects real content changes only.
        columns = [c[0] for c in self.con.execute(f"DESCRIBE {self.table_name}").fetchall()]
        select_cols = ", ".join(c for c in columns if c != "updated_at")
        rows = self.con.execute(  # noqa: S608 - table_name is caller-controlled, not user input
            f"SELECT {select_cols} FROM {self.table_name}"
        ).fetchall()
        return set(rows)
