"""Optional search evidence for instrumental-only tracks.

A web snippet alone is not proof of no vocals. This module only accepts a
track-specific, explicit instrumental-version designation from a source page;
all ambiguous search results remain unknown.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests


ALLOWED_HOSTS = {"bandcamp.com", "musicbrainz.org"}
VERSION_PATTERN = re.compile(r"\b(?:instrumental (?:version|mix|edit)|no[- ]vocals? version)\b", re.I)


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _host_allowed(host: str) -> bool:
    return host in ALLOWED_HOSTS or host.endswith(".bandcamp.com") or host.endswith(".musicbrainz.org")


def search_instrumental(artist: str, title: str) -> dict | None:
    """Ask Brave Search for recording-specific evidence when configured.

    Never infer instrumental status from a band's genre, a search query echoed in
    the snippet, or generic words such as 'instrumental rock'.
    """
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key or not artist.strip() or not title.strip():
        return None
    query = f'"{artist}" "{title}" instrumental version'
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": 5, "safesearch": "moderate"},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=8,
    )
    response.raise_for_status()
    hits = (response.json().get("web") or {}).get("results") or []
    for hit in hits:
        url = str(hit.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not _host_allowed((parsed.hostname or "").lower()):
            continue
        heading = str(hit.get("title") or "")
        description = re.sub(r"<[^>]*>", " ", str(hit.get("description") or ""))
        # Require artist and title in the indexed result rather than relying
        # on the search engine having matched the original query.
        aggregate = _normalized(heading + " " + description)
        if _normalized(artist) not in aggregate or _normalized(title) not in aggregate:
            continue
        # Explicitly labeled instrumental release only. An article calling
        # the *artist* instrumental is not recording-level confirmation.
        if not VERSION_PATTERN.search(heading):
            continue
        return {"status": "instrumental", "source": url, "method": "web track/version label"}
    return None
