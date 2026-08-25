"""Deterministic ids so re-running the pipeline is idempotent by construction:
the same natural key always hashes to the same id, so a second run upserts
the same row instead of creating a duplicate — no "does this already exist"
lookup needed before insert.
"""

import uuid

_NAMESPACE = uuid.UUID("c4c92d9a-2b1e-4c1a-9b0a-c4e1a5b6f7d0")  # arbitrary, fixed forever


def make_id(kind: str, natural_key: str) -> str:
    """kind is a short label like "place", "list", "tag", "category", "collection" —
    it's just there so the same natural_key under a different kind doesn't collide.
    """
    return str(uuid.uuid5(_NAMESPACE, f"{kind}:{natural_key}"))
