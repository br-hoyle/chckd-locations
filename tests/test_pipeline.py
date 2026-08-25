"""Exercises the foundation end to end against a throwaway DuckDB file:
migrate -> seed's dimension load -> run a real list -> re-run for
idempotency. This is the same path `chckd-lists` the CLI drives, just
pointed at a temp db so it never touches data/chckd.duckdb.
"""

from datetime import datetime, timezone

import pytest

from chckd_lists.db.connection import connect
from chckd_lists.db.migrate import migrate
from chckd_lists.ids import make_id
from chckd_lists.pipeline.load_dimensions import load_all_dimensions
from chckd_lists.pipeline.run import run_list


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.duckdb"
    migrate(db_path)
    con = connect(db_path)
    run_id = make_id("pipeline_run", f"test-seed:{datetime.now(timezone.utc).isoformat()}")
    con.execute(
        "INSERT INTO pipeline_runs (id, source_slug, started_at, status) VALUES (?, 'test-seed', ?, 'success')",
        [run_id, datetime.now(timezone.utc)],
    )
    load_all_dimensions(con, run_id)
    yield con
    con.close()


EXPECTED_TABLES = {
    "places",
    "lists",
    "list_tags",
    "place_tags",
    "list_places",
    "list_categories",
    "place_categories",
    "pipeline_runs",
    "table_change_log",
}


def test_migrate_creates_all_required_tables(db):
    tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
    assert EXPECTED_TABLES <= tables
    assert "tags" not in tables  # tags ARE place_categories, not a separate table — see CLAUDE.md
    assert "collections" not in tables  # removed for now — see CLAUDE.md
    assert "collection_lists" not in tables


def test_seed_loads_dimension_tables(db):
    assert db.execute("SELECT count(*) FROM place_categories").fetchone()[0] > 0
    assert db.execute("SELECT count(*) FROM list_categories").fetchone()[0] > 0


def test_run_static_list_populates_places_and_links_them(db):
    run_list(db, "the-seven-summits")

    place_count = db.execute("SELECT count(*) FROM places").fetchone()[0]
    list_places_count = db.execute("SELECT count(*) FROM list_places").fetchone()[0]
    assert place_count == 7
    assert list_places_count == 7

    everest_category = db.execute(
        """
        SELECT pc.full_path FROM places p
        JOIN place_categories pc ON pc.id = p.category_id
        WHERE p.name = 'Mount Everest'
        """
    ).fetchone()
    assert everest_category == ("natural.land.mountains.summit",)


def test_rerunning_a_list_is_idempotent(db):
    run_list(db, "the-seven-summits")
    run_list(db, "the-seven-summits")

    assert db.execute("SELECT count(*) FROM places").fetchone()[0] == 7
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 1

    second_run_logs = db.execute(
        """
        SELECT rows_added, rows_removed FROM table_change_log
        WHERE run_id = (SELECT id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1)
        """
    ).fetchall()
    assert all(added == 0 and removed == 0 for added, removed in second_run_logs)


def test_place_gets_tagged_with_its_full_taxonomy_ancestor_chain(db):
    run_list(db, "the-seven-summits")

    tag_paths = {
        row[0]
        for row in db.execute(
            """
            SELECT pc.full_path FROM places p
            JOIN place_tags pt ON pt.place_id = p.id
            JOIN place_categories pc ON pc.id = pt.category_id
            WHERE p.name = 'Mount Everest'
            """
        ).fetchall()
    }
    assert tag_paths == {"natural", "natural.land", "natural.land.mountains", "natural.land.mountains.summit"}


def test_list_gets_tagged_via_its_own_tags_field(db):
    run_list(db, "the-seven-summits")

    tag_paths = {
        row[0]
        for row in db.execute(
            """
            SELECT pc.full_path FROM lists l
            JOIN list_tags lt ON lt.list_id = l.id
            JOIN place_categories pc ON pc.id = lt.category_id
            WHERE l.slug = 'the-seven-summits'
            """
        ).fetchall()
    }
    assert tag_paths == {"natural", "natural.land", "natural.land.mountains", "natural.land.mountains.summit"}


def test_unimplemented_list_is_skipped_not_errored(db):
    run_list(db, "us-national-parks")  # status: stub (source.type: nps, but unverified — see CLAUDE.md)
    assert db.execute("SELECT count(*) FROM lists WHERE slug = 'us-national-parks'").fetchone()[0] == 0
