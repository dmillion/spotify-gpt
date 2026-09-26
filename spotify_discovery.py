"""Supplemental Spotify discovery helpers for sparse constrained searches."""
from __future__ import annotations

import logging

from activity_log import install_activity_capture
import spotify_playlist as spotify

# Install after app import but before any playlist request is handled. The capture
# mirrors only [Ollama] and [Tune Raider] lines into the browser terminal.
install_activity_capture()

# Keep Flask/Werkzeug localhost access lines out of both the in-app terminal and
# the development console so the diagnostic output stays focused on curation.
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def search_broad_context(
    token: str,
    term: str,
    *,
    heavy_preference: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Return broader Spotify results when an exact title search is too sparse.

    Unlike ``search_tracks_by_title_term``, this intentionally does not require the
    term to appear in the track title. It is only used as a fallback after exact
    matches have been exhausted, so the playlist can remain useful without hiding
    that the selection rule had to be relaxed.
    """
    term = str(term or "").strip()
    if not term:
        return []

    qualifiers = ["metal", "sludge", "doom", "hardcore", "grind", "stoner", "heavy"] if heavy_preference else []
    queries = [f'"{term}" {qualifier}' for qualifier in qualifiers]
    queries.extend([term, f'artist:"{term}"', f'album:"{term}"'])

    target = max(1, min(int(limit), 100))
    results: list[dict] = []
    seen_ids: set[str] = set()

    for query in queries:
        response = spotify.api_request(
            "GET",
            "/search",
            token,
            params={"q": query, "type": "track", "limit": 50},
        )
        for item in response.json().get("tracks", {}).get("items", []):
            track_id = str(item.get("id") or "").strip()
            if not track_id or track_id in seen_ids:
                continue
            seen_ids.add(track_id)
            results.append(item)
            if len(results) >= target:
                return results
    return results
