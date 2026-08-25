"""The contract every list source implements (pipeline step 2, "source all
locations for each list"). Deliberately one method: given the registry
entry for this list, return one dict per place using ConformedPlace's field
names (chckd_lists.schemas.models.ConformedPlace) — mapping the source's own
field names (e.g. NPS's "fullName"/"parkCode") onto ours is this module's
job, since it's the one that understands the source. pipeline/conform.py
then just validates the shape and resolves category_path/tags to db ids —
it doesn't know anything about individual sources.
"""

from abc import ABC, abstractmethod
from typing import Any


class ListSource(ABC):
    @abstractmethod
    def extract(self, list_entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Return one raw dict per place. list_entry is this list's parsed
        registry/lists/<slug>.yaml, in case the source needs config from it
        (e.g. an API query param)."""
