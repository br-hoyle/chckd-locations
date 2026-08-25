"""Loads the fully-derived dimension/hierarchy YAML (place_taxonomy,
list_categories) into DuckDB. These are wholesale re-derived from
registry/ every time — never hand-edited in the db, only in the YAML.
There is no separate tags-loading step: `tags` isn't a table (see
CLAUDE.md "Tags are place categories, not a separate concept") — a tag
reference is just a place_categories id, and place_categories is loaded
right here by load_place_categories.

(There's also no `collections` concept right now — the browsing hierarchy
over lists was pulled out for the time being; see CLAUDE.md "Collections
— removed for now" if it comes back.)

Every insert here is INSERT OR IGNORE, not an upsert: these two tables
are self-referencing trees, and DuckDB won't let an UPDATE touch a row
that's referenced by another row's foreign key (a documented limitation
for self-referential FKs), so ON CONFLICT DO UPDATE breaks on the second
run. Since ids are deterministic hashes of the node's path, a renamed
node's *content* changing (not its slug/path) is the only case this
misses — rare enough for a taxonomy that if it happens, drop
data/chckd.duckdb and re-migrate/seed from scratch rather than special-case
the update.

Run automatically as part of `chckd-lists seed`, since a freshly generated
registry is useless until its dimension tables exist.
"""

import logging

import duckdb

import yaml

from chckd_lists.config import LIST_CATEGORIES_YAML
from chckd_lists.db.diff import TableDiff
from chckd_lists.ids import make_id
from chckd_lists.pipeline.registry_loader import load_place_taxonomy

logger = logging.getLogger(__name__)


def load_place_categories(con: duckdb.DuckDBPyConnection, run_id: str) -> None:
    nodes = load_place_taxonomy()
    with TableDiff(con, run_id, "place_categories"):
        for node in nodes:
            node_id = make_id("place_category", node["full_path"])
            parent_id = make_id("place_category", node["parent_path"]) if node["parent_path"] else None
            con.execute(
                """
                INSERT OR IGNORE INTO place_categories (id, parent_id, level, name, slug, full_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [node_id, parent_id, node["level"], node["name"], node["full_path"].split(".")[-1], node["full_path"]],
            )


def load_list_categories_table(con: duckdb.DuckDBPyConnection, run_id: str) -> None:
    nodes = yaml.safe_load(LIST_CATEGORIES_YAML.read_text())
    with TableDiff(con, run_id, "list_categories"):
        for node in nodes:
            node_id = make_id("list_category", node["slug"])
            parent_id = make_id("list_category", node["parent_slug"]) if node.get("parent_slug") else None
            con.execute(
                """
                INSERT OR IGNORE INTO list_categories (id, parent_id, name, slug)
                VALUES (?, ?, ?, ?)
                """,
                [node_id, parent_id, node["name"], node["slug"]],
            )


def load_all_dimensions(con: duckdb.DuckDBPyConnection, run_id: str) -> None:
    # order matters: both tables are self-referencing trees inserted
    # parent-first (see registry_loader + the YAML's own sort order).
    load_place_categories(con, run_id)
    load_list_categories_table(con, run_id)
