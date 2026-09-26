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

SEARCH_PAGE_LIMIT = 10
SEARCH_MAX_OFFSET = 1000


def _search_pages(token: str, query: str, *, target: int) -> list[dict]:
    """Search Spotify in pages that comply with the current /search limit."""
    results: list[dict] = []
    offset = 0
    wanted = max(1, min(int(target), 100))

    while len(results) < wanted and offset <= SEARCH_MAX_OFFSET:
        response = spotify.api_request(
            "GET",
            "/search",
            token,
            params={
                "q": query,
                "type": "track",
                "limit": SEARCH_PAGE_LIMIT,
                "offset": offset,
            },
        )
        page = response.json().get("tracks", {})
        items = page.get("items", []) or []
        results.extend(items)
        if len(items) < SEARCH_PAGE_LIMIT or not page.get("next"):
            break
        offset += SEARCH_PAGE_LIMIT

    return results[:wanted]


def search_title_term(
    token: str,
    term: str,
    *,
    heavy_preference: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Discover tracks whose Spotify title literally contains ``term``.

    Spotify currently caps Search requests at 10 items, so this helper paginates
    instead of issuing one oversized request.
    """
    term = str(term or "").strip()
    needle = spotify.normalize(term)
    if not needle:
        return []

    qualifiers = ["metal", "sludge", "doom", "hardcore", "grind", "stoner"] if heavy_preference else []
    queries = [f'{term} {qualifier}' for qualifier in qualifiers]
    queries.extend([f'track:{term}', term])

    target = max(1, min(int(limit), 100))
    results: list[dict] = []
    seen_ids: set[str] = set()

    for query in queries:
        for item in _search_pages(token, query, target=target):
            track_id = str(item.get("id") or "").strip()
            if not track_id or track_id in seen_ids:
                continue
            if needle not in spotify.normalize(item.get("name", "")):
                continue
            seen_ids.add(track_id)
            results.append(item)
            if len(results) >= target:
                return results
    return results


# run_app historically calls spotify.search_tracks_by_title_term(). Replace that
# helper at import time so every title-constraint request uses the current paginated
# Search implementation without leaving the old limit=50 code path reachable.
spotify.search_tracks_by_title_term = search_title_term


def search_broad_context(
    token: str,
    term: str,
    *,
    heavy_preference: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Return broader Spotify results when an exact title search is too sparse.

    Unlike ``search_title_term``, this intentionally does not require the term to
    appear in the track title. It is only used after exact matches are exhausted.
    """
    term = str(term or "").strip()
    if not term:
        return []

    qualifiers = ["metal", "sludge", "doom", "hardcore", "grind", "stoner", "heavy"] if heavy_preference else []
    queries = [f'{term} {qualifier}' for qualifier in qualifiers]
    queries.extend([term, f'artist:{term}', f'album:{term}'])

    target = max(1, min(int(limit), 100))
    results: list[dict] = []
    seen_ids: set[str] = set()

    for query in queries:
        for item in _search_pages(token, query, target=target):
            track_id = str(item.get("id") or "").strip()
            if not track_id or track_id in seen_ids:
                continue
            seen_ids.add(track_id)
            results.append(item)
            if len(results) >= target:
                return results
    return results
