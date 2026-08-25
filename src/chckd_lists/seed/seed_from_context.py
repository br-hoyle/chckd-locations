"""One-time (but safe to re-run) generator: reads the source spreadsheet in
chckd-context/CHCKD-Taxonomy-Lists.xlsx and materializes the human-editable
registry/ content from it — place_taxonomy.yaml, list_categories.yaml, and
one lists/<slug>.yaml stub per row of the "Master List" sheet. There is no
tags.yaml: a tag IS a place_categories node (see CLAUDE.md "Tags are place
categories, not a separate concept"), so place_taxonomy.yaml is the only
file that needs to exist for tagging to work — nothing else to generate.
There's also no collections.yaml right now — the browsing hierarchy over
lists was pulled out for the time being (see CLAUDE.md "Collections —
removed for now").

Re-running overwrites place_taxonomy.yaml wholesale (it's fully derived
from the sheet), but never touches an existing lists/<slug>.yaml that's
already been hand-edited past its generated stub — see `_write_list_stub`.
That's the only asymmetry here, and it's deliberate: a list's registry
file is where a human fills in real `source:` config and (for static
lists) real place data, and a re-run of this script must not clobber that
work.

Run with: `chckd-lists seed`
"""

import logging
import re
from pathlib import Path

import openpyxl
import yaml

from chckd_lists.config import (
    LIST_CATEGORIES_YAML,
    LISTS_REGISTRY_DIR,
    PLACE_TAXONOMY_YAML,
    TAXONOMY_XLSX,
)

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _load_workbook():
    return openpyxl.load_workbook(TAXONOMY_XLSX, data_only=True)


# ---------------------------------------------------------------------------
# place_categories tree, from the "Taxonomy" sheet
# ---------------------------------------------------------------------------


def build_place_taxonomy(wb) -> list[dict]:
    ws = wb["Taxonomy"]
    rows = list(ws.iter_rows(values_only=True))[1:]  # skip header

    nodes: dict[str, dict] = {}  # full_path -> node, insertion order = level order
    for row in rows:
        collection, series, category, type_ = row[0], row[1], row[2], row[3]
        full_path = row[4]
        if not full_path:
            continue
        display_names = [v for v in (collection, series, category, type_) if v is not None]
        path_segments = full_path.split(".")
        if len(display_names) != len(path_segments):
            logger.warning("Skipping malformed taxonomy row %r — segment count mismatch", row)
            continue

        for level, (display_name, _segment) in enumerate(zip(display_names, path_segments)):
            node_path = ".".join(path_segments[: level + 1])
            if node_path in nodes:
                continue
            parent_path = ".".join(path_segments[:level]) or None
            nodes[node_path] = {
                "full_path": node_path,
                "parent_path": parent_path,
                "level": level,
                "name": display_name,
            }

    # parents-before-children order, so the loader can insert top-down without a second pass
    return sorted(nodes.values(), key=lambda n: (n["level"], n["full_path"]))


# ---------------------------------------------------------------------------
# lists/*.yaml stubs, from "Master List"
# ---------------------------------------------------------------------------


def _parse_approx_count(value) -> int | None:
    """Sheet values are usually a plain number, but some are strings like
    "~21" (approximate) — strip anything that isn't a digit. Numeric cells
    must be rounded, not string-stripped, or 7.0 turns into "70"."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def read_master_list_rows(wb) -> list[dict]:
    ws = wb["Master List"]
    rows = list(ws.iter_rows(values_only=True))[1:]  # skip header
    entries = []
    for tier, _tier_label, list_name, collection, dimension, governing_body, approx_count, notes in rows:
        if not list_name:
            continue  # tier section header row
        entries.append(
            {
                "tier": int(tier),
                "list_name": list_name,
                "collection": collection,
                "dimension": dimension,
                "governing_body": governing_body,
                "approx_count": _parse_approx_count(approx_count),
                "notes": notes,
            }
        )
    return entries


def build_list_categories(list_entries: list[dict]) -> list[dict]:
    """The flat "what domain is this list in" lookup (Regional / Natural /
    Place per the sheet's own Collection column) — a different, looser
    split than place_categories' natural/place/region. See CLAUDE.md."""
    seen: dict[str, dict] = {}
    for entry in list_entries:
        if not entry["collection"]:
            continue
        slug = slugify(entry["collection"])
        seen.setdefault(slug, {"slug": slug, "name": entry["collection"], "parent_slug": None})
    return sorted(seen.values(), key=lambda n: n["slug"])


def _list_stub_path(entry: dict) -> Path:
    slug = slugify(entry["list_name"])
    return LISTS_REGISTRY_DIR / f"tier-{entry['tier']}" / f"{slug}.yaml"


def _write_list_stub(entry: dict) -> None:
    slug = slugify(entry["list_name"])
    path = _list_stub_path(entry)
    if path.exists():
        logger.debug("%s already exists, leaving as-is", path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)

    stub = {
        "slug": slug,
        "name": entry["list_name"],
        "description": entry["notes"],
        "tier": entry["tier"],
        "list_category": slugify(entry["collection"]) if entry["collection"] else None,
        "governing_body": entry["governing_body"],
        "dimension": entry["dimension"],
        "approx_count": entry["approx_count"],
        "tags": [],
        "source": {
            "type": "unimplemented",
            "notes": "Fill in a real source (static place list, or an api-backed source module) and flip status to active.",
        },
        "status": "stub",
    }
    path.write_text(yaml.safe_dump(stub, sort_keys=False, allow_unicode=True))


def seed() -> None:
    LISTS_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    wb = _load_workbook()

    taxonomy_nodes = build_place_taxonomy(wb)
    PLACE_TAXONOMY_YAML.write_text(yaml.safe_dump(taxonomy_nodes, sort_keys=False, allow_unicode=True))
    logger.info("Wrote %d place_categories nodes to %s", len(taxonomy_nodes), PLACE_TAXONOMY_YAML)

    list_entries = read_master_list_rows(wb)

    list_categories = build_list_categories(list_entries)
    LIST_CATEGORIES_YAML.write_text(yaml.safe_dump(list_categories, sort_keys=False, allow_unicode=True))
    logger.info("Wrote %d list_categories to %s", len(list_categories), LIST_CATEGORIES_YAML)

    written = 0
    for entry in list_entries:
        before = _list_stub_path(entry).exists()
        _write_list_stub(entry)
        written += 0 if before else 1
    logger.info(
        "Wrote %d new list stubs (%d total rows) to %s, grouped into tier-1..tier-5 subfolders",
        written,
        len(list_entries),
        LISTS_REGISTRY_DIR,
    )


if __name__ == "__main__":
    from chckd_lists.logging_conf import setup_logging

    setup_logging()
    seed()
