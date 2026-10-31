"""Normalize candidate identities and prefer tracks absent from saved playlists."""
from __future__ import annotations

from collections import Counter
import json
import re
import unicodedata

from anchor_policy import _prompt_track_requests

ALIASES = {
    "osees": "thee oh sees",
    "the oh sees": "thee oh sees",
    "thee oh sees": "thee oh sees",
    "oh sees": "thee oh sees",
}


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def artist_key(artist):
    # Spotify's comma-separated artist credits sometimes include both aliases.
    parts = [norm(p) for p in str(artist or "").split(",")]
    return ALIASES.get(parts[0], parts[0]) if parts else ""


def track_key(track):
    return (artist_key(track.get("artist")), norm(track.get("title")))


def history_counts(connection):
    """Read existing playlist snapshots; no migration or separate tracking table."""
    counts = Counter()
    artists = Counter()
    rows = connection.execute("SELECT tracks FROM generated_playlists").fetchall()
    for row in rows:
        try:
            tracks = json.loads(row[0] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(tracks, list):
            continue
        unique = set()
        for track in tracks:
            if not isinstance(track, dict):
                continue
            key = track_key(track)
            if all(key):
                unique.add(key)
        for key in unique:
            counts[key] += 1
            artists[key[0]] += 1
    return counts, artists


def curate(prompt, generated, connection, *, artist_limit=2):
    """Keep references; demote historical repeats and alias-duplicate artists.

    Does not discard all repeated tracks when no fresh candidates exist.
    """
    references = {track_key({"artist": ref.artist, "title": ref.title})
                  for ref in _prompt_track_requests(prompt)}
    counts, artists = history_counts(connection)
    candidates = list(generated.get("tracks") or [])
    anchors = [t for t in candidates if track_key(t) in references]
    others = [t for t in candidates if track_key(t) not in references]
    # Stable ordering for equal history scores retains the model's relevance ranking.
    others.sort(key=lambda t: (counts[track_key(t)] * 10
                               + artists[artist_key(t.get("artist"))],
                               counts[track_key(t)]))
    selected = []
    seen = set()
    artist_usage = Counter()
    for track in anchors + others:
        key = track_key(track)
        if not all(key) or key in seen:
            continue
        if key not in references and artist_usage[key[0]] >= artist_limit:
            continue
        seen.add(key)
        artist_usage[key[0]] += 1
        selected.append(track)
    generated["tracks"] = selected
    print(f"[Tune Raider] novelty: {len(references)} references, "
          f"{len(candidates)} candidates -> {len(selected)} unique; "
          f"{sum(counts[track_key(t)] > 0 for t in selected if track_key(t) not in references)} historical repeats",
          flush=True)
    return generated
