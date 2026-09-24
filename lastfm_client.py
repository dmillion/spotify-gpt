#!/usr/bin/env python3
"""Small Last.fm client for artist tags used as genre/theme metadata."""

from __future__ import annotations

import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://ws.audioscrobbler.com/2.0/"
API_KEY = os.environ.get("LASTFM_API_KEY", "").strip()
SHARED_SECRET = os.environ.get("LASTFM_SHARED_SECRET", "").strip()

# Last.fm tags are user-generated. Keep musically useful descriptors, but strip
# obvious library-management, geography, chronology, and personal-opinion tags.
IGNORED_EXACT = {
    "seen live",
    "favorites",
    "favourites",
    "favorite",
    "favourite",
    "my favorites",
    "my favourites",
    "awesome",
    "best",
    "love",
    "loved",
    "albums i own",
    "owned",
    "spotify",
    "lastfm",
    "last.fm",
    "american",
    "british",
    "canadian",
    "australian",
    "german",
    "french",
    "swedish",
    "norwegian",
    "finnish",
    "japanese",
    "icelandic",
    "russian",
    "us",
    "usa",
    "uk",
}

IGNORED_PATTERNS = (
    re.compile(r"^(19|20)\d0s$"),
    re.compile(r"^(19|20)\d{2}$"),
    re.compile(r"^seen at\b"),
    re.compile(r"^from\b"),
)


def call(method: str, **params) -> dict:
    if not API_KEY:
        raise RuntimeError("LASTFM_API_KEY is not set.")
    response = requests.get(
        API_URL,
        params={
            "method": method,
            "api_key": API_KEY,
            "format": "json",
            "autocorrect": 1,
            **params,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(
            f"Last.fm error {payload['error']}: {payload.get('message', 'Unknown error')}"
        )
    return payload


def top_tags(artist: str) -> list[tuple[str, int]]:
    payload = call("artist.getTopTags", artist=artist)
    raw_tags = payload.get("toptags", {}).get("tag", [])
    tags: list[tuple[str, int]] = []
    for item in raw_tags:
        name = str(item.get("name") or "").strip()
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if name:
            tags.append((name, count))
    return tags


def is_useful_tag(name: str) -> bool:
    normalized = " ".join(name.casefold().split())
    if not normalized or normalized in IGNORED_EXACT:
        return False
    return not any(pattern.search(normalized) for pattern in IGNORED_PATTERNS)


def filtered_top_tags(
    artist: str,
    *,
    min_weight: int = 5,
    limit: int = 6,
) -> list[dict]:
    """Return strong, useful Last.fm tags with normalized names and weights."""
    result: list[dict] = []
    seen: set[str] = set()
    for raw_name, weight in top_tags(artist):
        name = " ".join(raw_name.strip().lower().split())
        if weight < min_weight or not is_useful_tag(name) or name in seen:
            continue
        result.append({"name": name, "weight": weight})
        seen.add(name)
        if len(result) >= limit:
            break
    return result


def top_tracks(artist: str, limit: int = 5) -> list[str]:
    payload = call("artist.getTopTracks", artist=artist, limit=limit)
    tracks = payload.get("toptracks", {}).get("track", [])
    return [
        str(track.get("name") or "").strip()
        for track in tracks
        if track.get("name")
    ]
