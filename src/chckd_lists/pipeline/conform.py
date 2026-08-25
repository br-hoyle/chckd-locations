"""Pipeline step 3: "conform to a defined schema." Pure validation — no DB
access here. Turns a source's raw dicts into ConformedPlace/ConformedList,
which either succeeds or raises pydantic.ValidationError with a clear
field-level message. Resolving category_path/tag slugs into actual db ids
happens later, in load.py, since that needs a connection.
"""

from typing import Any

from chckd_lists.schemas.models import ConformedList, ConformedPlace


def conform_places(raw_places: list[dict[str, Any]]) -> list[ConformedPlace]:
    return [ConformedPlace(**raw) for raw in raw_places]


def conform_list(list_entry: dict[str, Any]) -> ConformedList:
    return ConformedList(
        name=list_entry["name"],
        slug=list_entry["slug"],
        description=list_entry.get("description"),
        list_category_slug=list_entry.get("list_category"),
        tier=list_entry.get("tier"),
        governing_body=list_entry.get("governing_body"),
        dimension=list_entry.get("dimension"),
        approx_count=list_entry.get("approx_count"),
        source_url=list_entry.get("source_url"),
        tags=list_entry.get("tags", []),
    )
