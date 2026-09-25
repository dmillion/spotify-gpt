"""Post-curation safeguards for preserving explicitly named inspiration tracks/artists."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def _normalize(value: str) -> str:
    value = str(value or "").casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def _mentioned(prompt_normalized: str, value: str) -> bool:
    needle = _normalize(value)
    if not needle:
        return False
    return f" {needle} " in f" {prompt_normalized} "


def _load_tracks(database_path: Path) -> list[dict]:
    if not database_path.is_file():
        return []
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT artist, title, genre
            FROM tracks
            WHERE error IS NULL AND artist != '' AND title != ''
            ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE
            """
        ).fetchall()

    unique = {}
    for row in rows:
        key = (_normalize(row["artist"]), _normalize(row["title"]))
        unique.setdefault(
            key,
            {"artist": row["artist"], "title": row["title"], "genre": row["genre"] or ""},
        )
    return list(unique.values())


def _excluded_keys(excluded_tracks) -> set[tuple[str, str]]:
    result = set()
    for value in excluded_tracks or []:
        artist, separator, title = str(value).partition(" - ")
        if separator:
            result.add((_normalize(artist), _normalize(title)))
    return result


def _find_anchor(prompt: str, tracks: list[dict], excluded_tracks=None) -> dict | None:
    prompt_normalized = _normalize(prompt)
    if not prompt_normalized:
        return None

    artist_mentions = {
        _normalize(track["artist"])
        for track in tracks
        if _mentioned(prompt_normalized, track["artist"])
    }

    # Strongest signal: a track title explicitly present in the prompt. Short or
    # generic one-word titles only count when the artist is named too.
    song_matches = []
    for track in tracks:
        title_normalized = _normalize(track["title"])
        artist_normalized = _normalize(track["artist"])
        if not title_normalized or not _mentioned(prompt_normalized, track["title"]):
            continue
        title_is_distinctive = len(title_normalized) >= 8 and len(title_normalized.split()) >= 2
        if artist_normalized in artist_mentions or title_is_distinctive:
            song_matches.append(track)

    if song_matches:
        song_matches.sort(
            key=lambda track: (
                _normalize(track["artist"]) not in artist_mentions,
                -len(_normalize(track["title"])),
            )
        )
        return {**song_matches[0], "anchor_type": "song"}

    if not artist_mentions:
        return None

    # Prefer the longest explicit artist name so a specific name wins over a
    # shorter substring-like artist name. For regeneration, choose a different
    # track by that artist when possible before allowing a previous track back in.
    artist_key = max(artist_mentions, key=len)
    artist_tracks = [track for track in tracks if _normalize(track["artist"]) == artist_key]
    excluded = _excluded_keys(excluded_tracks)
    fresh = [
        track for track in artist_tracks
        if (_normalize(track["artist"]), _normalize(track["title"])) not in excluded
    ]
    chosen = (fresh or artist_tracks)[0] if (fresh or artist_tracks) else None
    return {**chosen, "anchor_type": "artist"} if chosen else None


def ensure_prompt_anchor(
    prompt: str,
    generated: dict,
    database_path: Path,
    *,
    excluded_tracks=None,
    track_limit: int = 20,
    artist_limit: int = 2,
) -> dict:
    """Guarantee a locally available prompt inspiration survives curation.

    The model is still responsible for sequencing and musical judgment. This only
    intervenes when an explicitly named local artist or song is missing entirely.
    """
    tracks = _load_tracks(database_path)
    anchor = _find_anchor(prompt, tracks, excluded_tracks)
    if not anchor:
        return generated

    selected = list(generated.get("tracks") or [])
    anchor_artist = _normalize(anchor["artist"])
    anchor_title = _normalize(anchor["title"])

    if anchor["anchor_type"] == "song":
        if any(
            _normalize(track.get("artist")) == anchor_artist
            and _normalize(track.get("title")) == anchor_title
            for track in selected
        ):
            return generated
    elif any(_normalize(track.get("artist")) == anchor_artist for track in selected):
        return generated

    # Keep the hard artist cap intact. For an explicitly named song, remove one
    # existing track by that artist if needed before inserting the anchor.
    same_artist_indexes = [
        index for index, track in enumerate(selected)
        if _normalize(track.get("artist")) == anchor_artist
    ]
    while len(same_artist_indexes) >= artist_limit:
        selected.pop(same_artist_indexes[-1])
        same_artist_indexes = [
            index for index, track in enumerate(selected)
            if _normalize(track.get("artist")) == anchor_artist
        ]

    selected.insert(
        0,
        {
            "artist": anchor["artist"],
            "title": anchor["title"],
            "source": "local-anchor",
        },
    )
    del selected[max(1, track_limit):]
    generated["tracks"] = selected

    print(
        f"[Tune Raider] enforced {anchor['anchor_type']} anchor: {anchor['artist']} - {anchor['title']}",
        flush=True,
    )
    return generated
