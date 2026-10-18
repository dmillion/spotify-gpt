"""LRCLIB evidence for strict instrumental-only playlist requests.

A missing lyrics record is never evidence of an instrumental performance.
All results are verified against recording identity before use.
"""
from __future__ import annotations

import re
import time

import requests

ROOT = "https://lrclib.net/api"
HEADERS = {"User-Agent": "TuneRaider/0.1 (https://github.com/dmillion/spotify-gpt)"}
_last_request = 0.0
_rate_limited_until = 0.0


def norm(value):
    return " ".join(re.sub(r"[^\w\s]", " ", str(value or "").casefold()).split())


def request(endpoint, params):
    global _last_request, _rate_limited_until
    if time.monotonic() < _rate_limited_until:
        return None
    pause = 0.3 - (time.monotonic() - _last_request)
    if pause > 0:
        time.sleep(pause)
    _last_request = time.monotonic()
    resp = requests.get(ROOT + endpoint, params=params, headers=HEADERS, timeout=8)
    if resp.status_code == 429:
        try:
            seconds = max(1.0, float(resp.headers.get("Retry-After", "60")))
        except (TypeError, ValueError):
            seconds = 60.0
        _rate_limited_until = time.monotonic() + seconds
        return None
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def evidence(artist, title, album=None, duration=None):
    """Return status instrumental/vocal or None.

    Exact signature when possible; otherwise use search and reject conflicting
    variants. Only a literal boolean instrumental field is meaningful.
    """
    if not artist or not title:
        return None
    duration_s = float(duration) if duration is not None else None
    candidates = None
    if album and duration_s and duration_s > 0:
        row = request("/get", {
            "artist_name": artist, "track_name": title,
            "album_name": album, "duration": round(duration_s),
        })
        if isinstance(row, dict):
            candidates = [row]
    if candidates is None:
        rows = request("/search", {"artist_name": artist, "track_name": title})
        if not isinstance(rows, list):
            return None
        candidates = rows
    matching = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        if norm(row.get("artistName")) != norm(artist) or norm(row.get("trackName")) != norm(title):
            continue
        if album and norm(row.get("albumName")) != norm(album):
            continue
        if duration_s and duration_s > 0:
            try:
                if abs(float(row.get("duration")) - duration_s) > 2:
                    continue
            except (TypeError, ValueError):
                continue
        if type(row.get("instrumental")) is not bool:
            continue
        matching.append(row)
    if not matching:
        return None
    statuses = {r["instrumental"] for r in matching}
    if len(statuses) > 1:
        return None
    is_instrumental = next(iter(statuses))
    # A contradictory entry (instrumental with lyrics) is unreliable.
    if is_instrumental and any(r.get("plainLyrics") or r.get("syncedLyrics") for r in matching):
        return None
    return {
        "status": "instrumental" if is_instrumental else "vocal",
        "source": f"https://lrclib.net/api/get/{matching[0]['id']}",
        "method": "LRCLIB instrumental flag",
    }
