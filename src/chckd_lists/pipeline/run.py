"""Orchestrates one list end to end: extract -> conform -> load, wrapped in
a pipeline_runs row and a TableDiff per table so changes get logged (the
"between runs, log changes to each table" requirement). This is the one
place that knows how to dispatch a registry entry's source.type to a
concrete ListSource — see registry/lists/*.yaml for the `source:` block.
"""

import logging
from datetime import datetime, timezone

import duckdb

from chckd_lists.db.diff import TableDiff
from chckd_lists.ids import make_id
from chckd_lists.pipeline.conform import conform_list, conform_places
from chckd_lists.pipeline.load import link_list_places, upsert_list, upsert_place
from chckd_lists.pipeline.registry_loader import load_list_entry
from chckd_lists.sources.base import ListSource
from chckd_lists.sources.nps import NPSParksSource
from chckd_lists.sources.protected_planet import ProtectedPlanetSource
from chckd_lists.sources.static import StaticSource

logger = logging.getLogger(__name__)

SOURCE_TYPES: dict[str, type[ListSource]] = {
    "static": StaticSource,
    "nps": NPSParksSource,
    "protected_planet": ProtectedPlanetSource,
}


def run_list(con: duckdb.DuckDBPyConnection, slug: str) -> None:
    list_entry = load_list_entry(slug)
    source_type = list_entry["source"]["type"]

    # `status` (not just source.type) gates whether `run --all` touches a
    # list — a list can have a real source module wired up (source.type:
    # protected_planet) and still be `stub` because nobody's found the
    # right designation_id / verified it against a live API key yet. Only
    # a human flipping status: active is a promise this list is ready to
    # actually write rows.
    if list_entry.get("status") != "active":
        logger.info("%s: status=%s, skipping", slug, list_entry.get("status"))
        return

    run_id = make_id("pipeline_run", f"{slug}:{datetime.now(timezone.utc).isoformat()}")
    con.execute(
        "INSERT INTO pipeline_runs (id, source_slug, started_at) VALUES (?, ?, ?)",
        [run_id, slug, datetime.now(timezone.utc)],
    )

    try:
        source_cls = SOURCE_TYPES[source_type]
        raw_places = source_cls().extract(list_entry)
        conformed_places = conform_places(raw_places)
        conformed_list = conform_list(list_entry)

        with TableDiff(con, run_id, "lists"):
            list_id = upsert_list(con, conformed_list)

        with TableDiff(con, run_id, "places"):
            place_ids = [upsert_place(con, place) for place in conformed_places]

        with TableDiff(con, run_id, "list_places"):
            link_list_places(con, list_id, place_ids)

        expected = conformed_list.approx_count
        if expected and len(place_ids) != expected:
            logger.warning(
                "%s: extracted %d places, registry expects ~%d — check the source",
                slug,
                len(place_ids),
                expected,
            )

        con.execute(
            "UPDATE pipeline_runs SET finished_at = ?, status = 'success' WHERE id = ?",
            [datetime.now(timezone.utc), run_id],
        )
        logger.info("%s: done (%d places)", slug, len(place_ids))
    except Exception:
        con.execute(
            "UPDATE pipeline_runs SET finished_at = ?, status = 'failed' WHERE id = ?",
            [datetime.now(timezone.utc), run_id],
        )
        logger.exception("%s: run failed", slug)
        raise
