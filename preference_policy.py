"""Small persistent preference rules shared by Tune Raider discovery/refinement."""
from __future__ import annotations

import os
import re


def normalize_artist(value: str) -> str:
    value = str(value or "").casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def blocked_artists() -> set[str]:
    """Return globally excluded artists.

    The env value is comma-separated so this remains user-configurable rather than
    requiring code changes for every future exclusion.
    """
    raw = os.environ.get("DISCOVERY_BLOCKED_ARTISTS", "Charley Crockett")
    return {
        normalize_artist(value)
        for value in raw.split(",")
        if normalize_artist(value)
    }


def artist_blocked(value: str) -> bool:
    return normalize_artist(value) in blocked_artists()
