"""Example API-backed source: NPS's public data API
(https://www.nps.gov/subjects/developer/api-documentation.htm).

Needs a free API key in the NPS_API_KEY env var — register at
https://www.nps.gov/subjects/developer/get-started.htm. This module is
here to show the pattern for an API source; it's wired to
registry/lists/tier-1/us-national-parks.yaml (source.type: nps) but still
status: stub since it needs a real key and network access to verify.
"""

import logging
import os
from typing import Any

import requests

from chckd_lists.sources.base import ListSource

logger = logging.getLogger(__name__)

API_URL = "https://developer.nps.gov/api/v1/parks"


class NPSParksSource(ListSource):
    def extract(self, list_entry: dict[str, Any]) -> list[dict[str, Any]]:
        api_key = os.environ.get("NPS_API_KEY")
        if not api_key:
            logger.warning("NPS_API_KEY not set — skipping %s", list_entry.get("slug"))
            return []

        category_path = list_entry["source"].get("category_path", "natural.park.national_park")
        params = {"designation": "National Park", "limit": 100, "api_key": api_key}
        response = requests.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        return [self._conform(park, category_path) for park in response.json()["data"]]

    @staticmethod
    def _conform(park: dict[str, Any], category_path: str) -> dict[str, Any]:
        return {
            "name": park["fullName"],
            "external_id": park["parkCode"],
            "external_id_source": "nps",
            "category_path": category_path,
            "lat": float(park["latitude"]) if park.get("latitude") else None,
            "lng": float(park["longitude"]) if park.get("longitude") else None,
            "admin_area_1": park.get("states"),
            "country_code": "US",
            "description": park.get("description"),
            "source_url": park.get("url"),
        }
