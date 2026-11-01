"""Evidence-aware ranking for prompts specifying sonic properties.

Only Spotify duration and Last.fm *track* tags count as measured evidence.
Artist tags are deliberately not substituted for recording-level evidence.
"""
from __future__ import annotations

from functools import lru_cache
import re

import lastfm_client as lastfm
from anchor_policy import _prompt_track_requests
from discovery_novelty import artist_key, norm

SIGNALS = {
    "drive": {"driving", "energetic", "high energy", "intense", "motorik", "uptempo", "upbeat"},
    "speed": {"fast", "fast paced", "fast tempo", "uptempo", "speed", "high bpm"},
    "abrasion": {"fuzz", "fuzzy", "distorted", "distortion", "noisy", "noise rock", "abrasive", "heavy", "garage punk"},
    "psych": {"psychedelic", "psychedelic rock", "psych rock", "krautrock", "space rock", "motorik"},
    "genre": {"garage rock", "garage punk", "psychedelic rock", "psych rock", "heavy psych", "acid rock"},
}
WEIGHTS = {"drive": 25, "speed": 20, "abrasion": 20, "psych": 15, "duration": 10, "genre": 10}


def intent(prompt):
    p = norm(prompt)
    return {
        "drive": bool(re.search(r"\b(driving|intense|energetic|aggressive|high energy|abrasive)\b", p)),
        "speed": bool(re.search(r"\b(fast|uptempo|high tempo|quick|rapid)\b", p)),
        "abrasion": bool(re.search(r"\b(heavy|abrasive|fuzz|distorted|noisy|aggressive)\b", p)),
        "psych": bool(re.search(r"\b(psych|psychedelic|krautrock|motorik)\b", p)),
        "duration": bool(re.search(r"\b(long|lengthy|extended|epic)\b", p)),
        "genre": bool(re.search(r"\b(psych|psychedelic|garage|rock)\b", p)),
    }


@lru_cache(maxsize=2048)
def track_tags(artist, title):
    if not lastfm.API_KEY:
        return ()
    try:
        payload = lastfm.call("track.getTopTags", artist=artist, track=title)
        tags = payload.get("toptags", {}).get("tag", [])
        return tuple(norm(t.get("name")) for t in tags
                     if lastfm.is_useful_tag(str(t.get("name") or "")))
    except Exception as exc:
        print(f"[Tune Raider] sonic tags unavailable for {artist} - {title}: {exc}", flush=True)
        return ()


def score(prompt, track, *, tags=None):
    active = intent(prompt)
    artists = track.get("artists") or []
    artist = str((artists[0] if artists else {}).get("name") or "")
    title = str(track.get("name") or "")
    if tags is None:
        tags = track_tags(artist, title)
    tags = set(norm(t) for t in tags)
    duration = track.get("duration_ms")
    evidence = {}
    for dimension in ("drive", "speed", "abrasion", "psych", "genre"):
        if active[dimension]:
            hits = sorted(tags & {norm(t) for t in SIGNALS[dimension]})
            if hits:
                evidence[dimension] = hits
    if active["duration"] and isinstance(duration, (int, float)) and duration > 0:
        evidence["duration"] = round(duration / 60000, 2)
    # Unknown dimensions are not assumed negative. A confirmed extended
    # recording gets a bonus; short recordings receive no duration bonus.
    points = sum(WEIGHTS[d] for d in evidence if d != "duration")
    if "duration" in evidence:
        minutes = evidence["duration"]
        points += WEIGHTS["duration"] * max(0, min(1, (minutes - 3) / 4))
    return round(points, 2), evidence


def rank(prompt, tracks):
    references = {(artist_key(ref.artist), norm(ref.title))
                  for ref in _prompt_track_requests(prompt)}
    indexed = []
    for index, track in enumerate(tracks):
        artist = str(((track.get("artists") or [{}])[0]).get("name") or "")
        key = (artist_key(artist), norm(track.get("name")))
        if key in references:
            indexed.append((0, index, track))
            continue
        points, evidence = score(prompt, track)
        indexed.append((1, -points, index, track))
        print(f"[Tune Raider] sonic: {artist} - {track.get('name')}: "
              f"score={points}, evidence={evidence or 'unknown'}", flush=True)
    # Explicit anchors first, then evidence scores; original model order breaks ties.
    indexed.sort(key=lambda row: row[:2] if len(row) == 3 else row[:3])
    return [row[-1] for row in indexed]
