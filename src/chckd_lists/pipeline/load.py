"""Pipeline steps 4-6: apply tags, upsert the list + its places, and wire up
list_tags/place_tags/list_places. Everything is an upsert keyed on a
deterministic id (chckd_lists.ids.make_id), so re-running a list is safe.

There's no separate "tag" entity here — see CLAUDE.md "Tags are place
categories, not a separate concept". Tagging a place or list just means
pointing it at one or more place_categories nodes, via place_tags/list_tags.
`ConformedPlace.tags` / `ConformedList.tags` hold place_categories
`full_path` strings (e.g. "natural.water.coastal"), not arbitrary slugs.

DuckDB has no native UPSERT-with-ignore-on-conflict shorthand we lean on
everywhere here, so we use `ON CONFLICT ... DO UPDATE` for tables that are
genuinely re-scraped each run (places, lists), and `INSERT OR IGNORE` for
join tables and the self-referencing dimension trees. See CLAUDE.md
"Upsert conventions" if this needs revisiting.
"""

import logging
from datetime import datetime, timezone

import duckdb

from chckd_lists.ids import make_id
from chckd_lists.schemas.models import ConformedList, ConformedPlace

logger = logging.getLogger(__name__)


def taxonomy_ancestor_category_ids(category_path: str | None) -> list[str]:
    """A place/list tagged with e.g. "natural.land.mountains.summit" gets
    every ancestor too (natural, natural.land, natural.land.mountains,
    natural.land.mountains.summit) — not just that one leaf — so browsing
    by the broad "natural" tag or the specific "summit" tag both work.
    Ids are computed directly rather than looked up: a place_categories id
    is a deterministic hash of its full_path (see
    load_dimensions.py::load_place_categories), valid as long as
    `chckd-lists seed` has already loaded the table.
    """
    if not category_path:
        return []
    segments = category_path.split(".")
    return [make_id("place_category", ".".join(segments[: i + 1])) for i in range(len(segments))]


def resolve_category_id(con: duckdb.DuckDBPyConnection, category_path: str | None) -> str | None:
    if not category_path:
        return None
    row = con.execute(
        "SELECT id FROM place_categories WHERE full_path = ?", [category_path]
    ).fetchone()
    if row is None:
        logger.warning("Unknown place category path %r — leaving place uncategorized", category_path)
        return None
    return row[0]


def resolve_list_category_id(con: duckdb.DuckDBPyConnection, slug: str | None) -> str | None:
    if not slug:
        return None
    row = con.execute("SELECT id FROM list_categories WHERE slug = ?", [slug]).fetchone()
    if row is None:
        logger.warning("Unknown list category slug %r — leaving list uncategorized", slug)
        return None
    return row[0]


def upsert_place(con: duckdb.DuckDBPyConnection, place: ConformedPlace) -> str:
    place_id = make_id("place", f"{place.external_id_source}:{place.external_id}")
    category_id = resolve_category_id(con, place.category_path)
    now = datetime.now(timezone.utc)

    con.execute(
        """
        INSERT INTO places (
            id, name, category_id, external_id, external_id_source,
            lat, lng, formatted_address, locality, admin_area_1, admin_area_2,
            country_code, description, source_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (external_id_source, external_id) DO UPDATE SET
            name = excluded.name,
            category_id = excluded.category_id,
            lat = excluded.lat,
            lng = excluded.lng,
            formatted_address = excluded.formatted_address,
            locality = excluded.locality,
            admin_area_1 = excluded.admin_area_1,
            admin_area_2 = excluded.admin_area_2,
            country_code = excluded.country_code,
            description = excluded.description,
            source_url = excluded.source_url,
            updated_at = excluded.updated_at
        """,
        [
            place_id,
            place.name,
            category_id,
            place.external_id,
            place.external_id_source,
            place.lat,
            place.lng,
            place.formatted_address,
            place.locality,
            place.admin_area_1,
            place.admin_area_2,
            place.country_code,
            place.description,
            place.source_url,
            now,
            now,
        ],
    )

    if category_id:  # only if category_path resolved — an unknown path leaves the place untagged, not half-tagged
        for cat_id in taxonomy_ancestor_category_ids(place.category_path):
            con.execute("INSERT OR IGNORE INTO place_tags (place_id, category_id) VALUES (?, ?)", [place_id, cat_id])

    for extra_path in place.tags:
        if resolve_category_id(con, extra_path) is None:
            continue  # unknown path — already warned inside resolve_category_id
        for cat_id in taxonomy_ancestor_category_ids(extra_path):
            con.execute("INSERT OR IGNORE INTO place_tags (place_id, category_id) VALUES (?, ?)", [place_id, cat_id])

    return place_id


def upsert_list(con: duckdb.DuckDBPyConnection, conformed_list: ConformedList) -> str:
    list_id = make_id("list", conformed_list.slug)
    category_id = resolve_list_category_id(con, conformed_list.list_category_slug)
    now = datetime.now(timezone.utc)

    con.execute(
        """
        INSERT INTO lists (
            id, name, slug, description, category_id, tier, governing_body,
            dimension, approx_count, status, source_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT (slug) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            category_id = excluded.category_id,
            tier = excluded.tier,
            governing_body = excluded.governing_body,
            dimension = excluded.dimension,
            approx_count = excluded.approx_count,
            status = excluded.status,
            source_url = excluded.source_url,
            updated_at = excluded.updated_at
        """,
        [
            list_id,
            conformed_list.name,
            conformed_list.slug,
            conformed_list.description,
            category_id,
            conformed_list.tier,
            conformed_list.governing_body,
            conformed_list.dimension,
            conformed_list.approx_count,
            conformed_list.source_url,
            now,
            now,
        ],
    )

    for extra_path in conformed_list.tags:
        if resolve_category_id(con, extra_path) is None:
            continue  # unknown path — already warned inside resolve_category_id
        for cat_id in taxonomy_ancestor_category_ids(extra_path):
            con.execute("INSERT OR IGNORE INTO list_tags (list_id, category_id) VALUES (?, ?)", [list_id, cat_id])

    return list_id


def link_list_places(con: duckdb.DuckDBPyConnection, list_id: str, place_ids: list[str]) -> None:
    for sort_order, place_id in enumerate(place_ids):
        con.execute(
            "INSERT OR IGNORE INTO list_places (list_id, place_id, sort_order) VALUES (?, ?, ?)",
            [list_id, place_id, sort_order],
        )
