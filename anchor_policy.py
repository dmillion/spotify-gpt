"""Post-curation safeguards for preserving explicitly named inspiration tracks/artists."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import spotify_playlist as spotify


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


def _prompt_track_request(prompt: str) -> spotify.TrackRequest | None:
    """Extract common explicit `track by artist` inspiration phrasing.

    This intentionally stays conservative: it is only a fallback when the local
    library could not identify an anchor, and the Spotify resolver must still find
    a sufficiently close canonical match before anything is inserted.
    """
    text = " ".join(str(prompt or "").split())
    if not text:
        return None

    patterns = [
        r"(?:songs?|tracks?|music)\s+like\s+[\"']?(?P<title>.+?)[\"']?\s+by\s+(?P<artist>.+?)(?=\s+(?:where|with|that|which|because|but|and\s+there|and\s+it)\b|[,.;]|$)",
        r"(?:like|similar\s+to|based\s+on|inspired\s+by)\s+[\"']?(?P<title>.+?)[\"']?\s+by\s+(?P<artist>.+?)(?=\s+(?:where|with|that|which|because|but|and\s+there|and\s+it)\b|[,.;]|$)",
        r"[\"']?(?P<title>[A-Z0-9][^,;]{1,80}?)[\"']?\s+by\s+(?P<artist>[A-Z0-9][^,;]{1,80}?)(?=\s+(?:where|with|that|which|because|but)\b|[,.;]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        title = match.group("title").strip(" \"'“”‘’")
        artist = match.group("artist").strip(" \"'“”‘’")
        if title and artist and len(title) <= 120 and len(artist) <= 120:
            return spotify.TrackRequest(artist=artist, title=title)
    return None


def _spotify_prompt_anchor(prompt: str) -> dict | None:
    requested = _prompt_track_request(prompt)
    if not requested:
        return None

    token_info = spotify.load_token()
    if not token_info or not spotify.token_has_required_scopes(token_info):
        return None
    token = str(token_info.get("access_token") or "").strip()
    if not token:
        return None

    try:
        match = spotify.search_track(token, requested)
    except Exception:
        return None
    if not match:
        return None

    artists = match.get("artists") or []
    artist = str((artists[0] if artists else {}).get("name") or requested.artist).strip()
    title = str(match.get("name") or requested.title).strip()
    if not artist or not title:
        return None
    return {"artist": artist, "title": title, "genre": "", "anchor_type": "song", "source": "spotify-anchor"}


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
        return {**song_matches[0], "anchor_type": "song", "source": "local-anchor"}

    if artist_mentions:
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
        if chosen:
            return {**chosen, "anchor_type": "artist", "source": "local-anchor"}

    # The inspiration track may not exist in the local MP3 library. If the prompt
    # explicitly says "Track by Artist", try Spotify before giving up on the anchor.
    return _spotify_prompt_anchor(prompt)


def _description_mentions_missing_entity(description: str, selected: list[dict], catalog: list[dict]) -> bool:
    normalized_description = _normalize(description)
    if not normalized_description:
        return False

    selected_artists = {_normalize(track.get("artist")) for track in selected}
    selected_titles = {_normalize(track.get("title")) for track in selected}

    # Catch references to known catalog artists/tracks that are not actually in
    # the final curated track list. Long names are checked first to avoid substring
    # ambiguity with shorter artist names.
    catalog_artists = sorted({_normalize(track["artist"]) for track in catalog if track.get("artist")}, key=len, reverse=True)
    catalog_titles = sorted({_normalize(track["title"]) for track in catalog if track.get("title")}, key=len, reverse=True)
    padded = f" {normalized_description} "

    for artist in catalog_artists:
        if len(artist) >= 4 and artist not in selected_artists and f" {artist} " in padded:
            return True
    for title in catalog_titles:
        if len(title) >= 8 and title not in selected_titles and f" {title} " in padded:
            return True

    # Also catch the most common hallucinated attribution even when that artist is
    # not in the local catalog: "anchored by X", "featuring X", etc. If the named
    # phrase does not match any selected artist, discard the description rather than
    # claim the playlist contains something it does not.
    for pattern in (
        r"\banchored\s+by\s+([^,.]+)",
        r"\bfeaturing\s+([^,.]+)",
        r"\bbuilt\s+around\s+([^,.]+)",
        r"\bcentered\s+(?:on|around)\s+([^,.]+)",
    ):
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = _normalize(match.group(1).split("'s", 1)[0].strip())
        if phrase and not any(artist and artist in phrase or phrase in artist for artist in selected_artists):
            return True
    return False


def _ground_description(generated: dict, catalog: list[dict]) -> dict:
    selected = list(generated.get("tracks") or [])
    description = str(generated.get("description") or "").strip()
    if not selected or not description:
        return generated
    if not _description_mentions_missing_entity(description, selected, catalog):
        return generated

    # Do not invent a replacement artist/track attribution. Keep the description
    # useful but entity-neutral when the model referenced something it did not pick.
    generated["description"] = "A curated playlist built around the requested sound, with musically adjacent picks chosen from the final track set."
    print("[Tune Raider] replaced ungrounded playlist description", flush=True)
    return generated


def ensure_prompt_anchor(
    prompt: str,
    generated: dict,
    database_path: Path,
    *,
    excluded_tracks=None,
    track_limit: int = 20,
    artist_limit: int = 2,
) -> dict:
    """Guarantee a resolvable prompt inspiration survives curation when possible.

    The model remains responsible for sequencing and musical judgment. This only
    intervenes when an explicitly named local or Spotify-resolvable artist/song is
    missing, then validates that the description does not name absent catalog items.
    """
    tracks = _load_tracks(database_path)
    anchor = _find_anchor(prompt, tracks, excluded_tracks)
    selected = list(generated.get("tracks") or [])

    if anchor:
        anchor_artist = _normalize(anchor["artist"])
        anchor_title = _normalize(anchor["title"])
        present = False

        if anchor["anchor_type"] == "song":
            present = any(
                _normalize(track.get("artist")) == anchor_artist
                and _normalize(track.get("title")) == anchor_title
                for track in selected
            )
        else:
            present = any(_normalize(track.get("artist")) == anchor_artist for track in selected)

        if not present:
            # Keep the hard artist cap intact. For an explicitly named song, remove
            # one existing track by that artist if needed before inserting the anchor.
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
                    "source": str(anchor.get("source") or "anchor"),
                },
            )
            del selected[max(1, track_limit):]
            generated["tracks"] = selected

            print(
                f"[Tune Raider] enforced {anchor['anchor_type']} anchor: {anchor['artist']} - {anchor['title']}",
                flush=True,
            )

    return _ground_description(generated, tracks)
