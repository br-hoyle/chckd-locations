"""Source type for lists with a small, fixed membership that doesn't change
and isn't worth calling an API for (e.g. "Seven Summits", "Five Oceans").
The raw records live directly in registry/lists/<slug>.yaml under `places:`
— see registry/lists/seven-summits.yaml for the shape.
"""

from typing import Any

from chckd_lists.sources.base import ListSource


class StaticSource(ListSource):
    def extract(self, list_entry: dict[str, Any]) -> list[dict[str, Any]]:
        return list_entry["source"].get("places", [])
