"""Small MusicBrainz client for Tune Raider enrichment/discovery.

MusicBrainz requires a meaningful User-Agent and asks clients to stay at or below
roughly one request per second. This module keeps a tiny in-memory cache and
serializes requests so playlist generation does not hammer the public service.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

API_BASE = "https://musicbrainz.org/ws/2"
ENABLED = os.environ.get("MUSICBRAINZ_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
USER_AGENT = os.environ.get(
    "MUSICBRAINZ_USER_AGENT",
    "TuneRaider/1.0 (https://github.com/dmillion/spotify-gpt)",
).strip()
TIMEOUT = max(1, int(os.environ.get("MUSICBRAINZ_TIMEOUT", "15")))
MIN_INTERVAL = max(1.0, float(os.environ.get("MUSICBRAINZ_MIN_INTERVAL", "1.05")))

_cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}
_lock = threading.Lock()
_last_request_at = 0.0


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("&", " and ").split())


def _request(path: str, **params) -> dict[str, Any]:
    global _last_request_at
    if not ENABLED:
        return {}
    clean_params = {str(key): str(value) for key, value in params.items() if value not in (None, "")}
    clean_params["fmt"] = "json"
    key = (path, tuple(sorted(clean_params.items())))
    cached = _cache.get(key)
    if cached is not None:
        return cached

    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        response = requests.get(
            f"{API_BASE}/{path.lstrip('/')}",
            params=clean_params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        _last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        _cache[key] = payload
        return payload


def search_artist(name: str) -> dict[str, Any] | None:
    """Return the best MusicBrainz artist match for a display name."""
    name = str(name or "").strip()
    if not name:
        return None
    payload = _request("artist", query=f'artist:"{name}"', limit=5)
    artists = payload.get("artists") or []
    if not isinstance(artists, list):
        return None
    needle = _normalize(name)
    exact = [artist for artist in artists if _normalize(artist.get("name", "")) == needle]
    pool = exact or artists
    if not pool:
        return None
    return max(pool, key=lambda artist: int(artist.get("score") or 0))


def artist_details(name: str) -> dict[str, Any]:
    artist = search_artist(name)
    mbid = str((artist or {}).get("id") or "").strip()
    if not mbid:
        return {}
    return _request(f"artist/{mbid}", inc="tags+artist-rels")


def artist_tags(name: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return weighted community tags for an artist."""
    try:
        details = artist_details(name)
    except (requests.RequestException, ValueError):
        return []
    tags = details.get("tags") or []
    result = []
    for tag in tags:
        tag_name = str(tag.get("name") or "").strip()
        if not tag_name:
            continue
        result.append({"name": tag_name, "count": int(tag.get("count") or 0)})
    result.sort(key=lambda item: item["count"], reverse=True)
    return result[: max(0, limit)]


def related_artists(name: str, *, limit: int = 10) -> list[str]:
    """Return artist-to-artist relationships that are useful as light discovery hints."""
    try:
        details = artist_details(name)
    except (requests.RequestException, ValueError):
        return []
    ignored_types = {"member of band", "founder", "instrument", "vocal", "producer", "engineer", "mix", "mastering"}
    seen = set()
    result = []
    for relation in details.get("relations") or []:
        if relation.get("target-type") != "artist":
            continue
        relation_type = str(relation.get("type") or "").casefold()
        if relation_type in ignored_types:
            continue
        artist = relation.get("artist") or {}
        candidate = str(artist.get("name") or "").strip()
        key = _normalize(candidate)
        if not candidate or not key or key == _normalize(name) or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def recordings_by_artist(name: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Return distinct recordings credited to an artist, ordered by MB search relevance."""
    name = str(name or "").strip()
    if not name:
        return []
    try:
        payload = _request("recording", query=f'artist:"{name}"', limit=max(1, min(limit * 2, 25)))
    except (requests.RequestException, ValueError):
        return []
    needle = _normalize(name)
    seen = set()
    result = []
    for recording in payload.get("recordings") or []:
        title = str(recording.get("title") or "").strip()
        credits = recording.get("artist-credit") or []
        credited_names = []
        for credit in credits:
            artist = credit.get("artist") if isinstance(credit, dict) else None
            credited = str((artist or {}).get("name") or "").strip()
            if credited:
                credited_names.append(credited)
        if not title or not credited_names or needle not in {_normalize(value) for value in credited_names}:
            continue
        key = (_normalize(credited_names[0]), _normalize(title))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "artist": credited_names[0],
            "title": title,
            "source": "musicbrainz",
            "musicbrainz_id": recording.get("id"),
            "score": int(recording.get("score") or 0),
        })
        if len(result) >= limit:
            break
    return result
