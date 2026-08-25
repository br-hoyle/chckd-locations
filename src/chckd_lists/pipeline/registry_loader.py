"""Reads registry/ — the human-editable content that step 1 ("a hierarchy
that easily allows me to add/remove lists") is all about. Add a list: drop
a new registry/lists/tier-<n>/<slug>.yaml (tier folders keep the directory
navigable at 90+ lists — see CLAUDE.md "Registry pattern"). Remove a list:
delete the file (its rows can be dropped by re-running migrate against a
fresh db, or left as status="deprecated" if you want to keep history).
"""

from typing import Any

import yaml

from chckd_lists.config import LISTS_REGISTRY_DIR, PLACE_TAXONOMY_YAML


def load_list_entry(slug: str) -> dict[str, Any]:
    matches = list(LISTS_REGISTRY_DIR.glob(f"tier-*/{slug}.yaml"))
    if not matches:
        raise FileNotFoundError(f"No registry/lists/tier-*/{slug}.yaml found")
    if len(matches) > 1:
        raise ValueError(f"Slug {slug!r} matches more than one file: {matches}")
    return yaml.safe_load(matches[0].read_text())


def load_all_list_entries() -> list[dict[str, Any]]:
    return [yaml.safe_load(p.read_text()) for p in sorted(LISTS_REGISTRY_DIR.glob("tier-*/*.yaml"))]


def load_place_taxonomy() -> list[dict[str, Any]]:
    return yaml.safe_load(PLACE_TAXONOMY_YAML.read_text())
