"""Protected Planet (WDPA — World Database on Protected Areas) API v4:
https://api.protectedplanet.net/documentation

This is the broad workhorse for almost every "US National ___" /
"___ Parks" / "___ Reserves" style list in the registry: national parks,
state parks, wildlife refuges, national monuments, marine sanctuaries,
Ramsar wetlands, biosphere reserves, and their international equivalents
are all tracked as "protected areas" in WDPA, each carrying a `designation`
(e.g. "National Park", "State Park", "Wilderness Area") and an ISO3
country code. One source module, many lists — see registry/lists/*.yaml's
`source.params` for the filters each list uses.

Auth: a free API token (request one at https://api.protectedplanet.net/request),
passed as the `token` query param — set PROTECTED_PLANET_API_KEY.

Search requires at least one filter (`country`, `marine`, `designation`,
`iucn_category`, `governance`, or `jurisdiction`). `designation` and the
other classification filters are *integer ids*, not names — the API
doesn't document a fixed id table, so finding the right id for e.g. "US
National Park" means an exploratory call (no filter but `country: USA`,
`per_page: 50`, look at the `designation` object on the results) done once
per list and pasted into that list's registry YAML as `designation_id`.
That lookup — and a real run against a real token — hasn't happened yet;
see registry/lists/*/*.yaml entries with source.type: protected_planet,
all still status: stub until someone does that and verifies a run.
"""

import logging
import os
from typing import Any

import requests

from chckd_lists.sources.base import ListSource

logger = logging.getLogger(__name__)

API_URL = "https://api.protectedplanet.net/v4/protected_areas/search"
PER_PAGE = 50  # API max


class ProtectedPlanetSource(ListSource):
    def extract(self, list_entry: dict[str, Any]) -> list[dict[str, Any]]:
        api_key = os.environ.get("PROTECTED_PLANET_API_KEY")
        if not api_key:
            logger.warning("PROTECTED_PLANET_API_KEY not set — skipping %s", list_entry.get("slug"))
            return []

        source_cfg = list_entry["source"]
        filters = source_cfg.get("params", {})
        if not filters:
            logger.warning(
                "%s: protected_planet source has no `params` filters configured "
                "(search requires at least one — country/designation_id/marine/iucn_category)",
                list_entry.get("slug"),
            )
            return []

        category_path = source_cfg.get("category_path", "natural.park")
        places, page = [], 1
        while True:
            response = requests.get(
                API_URL,
                params={"token": api_key, "page": page, "per_page": PER_PAGE, **filters},
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
            protected_areas = body.get("protected_areas", [])
            if not protected_areas:
                break
            places.extend(self._conform(pa, category_path) for pa in protected_areas)
            if len(protected_areas) < PER_PAGE:
                break
            page += 1

        return places

    @staticmethod
    def _conform(pa: dict[str, Any], category_path: str) -> dict[str, Any]:
        countries = pa.get("countries") or []
        country_code = countries[0].get("iso_3") if countries else pa.get("parent_iso3")
        designation = (pa.get("designation") or {}).get("name")

        return {
            "name": pa.get("name") or pa.get("name_english"),
            "external_id": str(pa["site_id"]),
            "external_id_source": "protected_planet",
            "category_path": category_path,
            # No lat/lng here: with_geometry is left off by default (most
            # protected areas are large polygons, not points — a real
            # centroid needs a geometry library we haven't added, see
            # CLAUDE.md roadmap on geocoding). Coordinates get filled in by
            # a later enrichment pass, not this source.
            "lat": None,
            "lng": None,
            "country_code": country_code,
            "description": designation,
            "source_url": (pa.get("links") or {}).get("protected_planet"),
        }
