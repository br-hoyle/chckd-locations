"""The "conformed" shape every source's raw records get mapped into before
loading (pipeline step 3, "conform to a defined schema"). One file, plain
pydantic models — no need to split into a package for six small classes.

These mirror db/schema.sql column-for-column on purpose: a model instance's
.model_dump() maps directly onto an INSERT. If a table gains a column, add
the field here in the same change.
"""

from pydantic import BaseModel


class ConformedPlace(BaseModel):
    name: str
    external_id: str
    external_id_source: str  # "nps", "unesco", "wikidata", "manual", ...
    category_path: str | None = None  # dotted path into place_categories.full_path, e.g. "natural.park"
    lat: float | None = None
    lng: float | None = None
    formatted_address: str | None = None
    locality: str | None = None
    admin_area_1: str | None = None
    admin_area_2: str | None = None
    country_code: str | None = None
    description: str | None = None
    source_url: str | None = None
    # Additional place_categories.full_path strings beyond category_path
    # (e.g. a state park that's also on the coast: category_path
    # "natural.park.state_park", tags ["natural.water.coastal"]). A tag IS
    # a place_categories node — see CLAUDE.md "Tags are place categories,
    # not a separate concept". Each gets its full ancestor chain attached
    # too, same as category_path does.
    tags: list[str] = []


class ConformedList(BaseModel):
    name: str
    slug: str
    description: str | None = None
    list_category_slug: str | None = None
    tier: int | None = None
    governing_body: str | None = None
    dimension: str | None = None
    approx_count: int | None = None
    source_url: str | None = None
    tags: list[str] = []  # place_categories.full_path strings — same meaning as ConformedPlace.tags
