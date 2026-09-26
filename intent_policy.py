"""Deterministic safeguards for literal title/name search prompts.

The LLM is good at musical curation, but a lexical request such as
"songs with goat in the name, ideally heavy" must not turn a title match into
an artist/genre anchor. This module preserves the literal constraint after
curation and supplements it with matching local-library tracks.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


HEAVY_TERMS = (
    "heavy", "metal", "sludge", "doom", "stoner", "hardcore", "grind",
    "grindcore", "death", "black metal", "noise rock", "post-metal",
)
HEAVY_GENRE_TERMS = (
    "metal", "sludge", "doom", "stoner", "hardcore", "grind", "death",
    "black", "noise", "post-metal", "punk", "heavy psych",
)


def _normalize(value: str) -> str:
    value = str(value or "").casefold()
    value = re.sub(r"[^\w\s-]", " ", value)
    return " ".join(value.split())


def _clean_term(value: str) -> str:
    value = str(value or "").strip(" \t\r\n'\".,;:!?()[]{}")
    value = re.sub(r"\s+", " ", value)
    return value


def title_constraint(prompt: str) -> dict | None:
    """Return a literal title/name constraint when the prompt clearly contains one.

    This intentionally handles high-confidence wording only. Ambiguous prompts stay
    with normal LLM curation rather than being over-parsed.
    """
    text = " ".join(str(prompt or "").strip().split())
    if not text:
        return None

    patterns = (
        # "songs with the word goat in the name/title"
        r"\b(?:songs?|tracks?)\s+(?:that\s+)?(?:have|has|with|containing|including)\s+(?:the\s+word\s+)?[\"']?([^\"']+?)[\"']?\s+in\s+(?:their\s+|the\s+)?(?:name|title)s?\b",
        # "songs with the name goat in them"
        r"\b(?:songs?|tracks?)\s+(?:that\s+)?(?:have|has|with|containing|including)\s+(?:the\s+)?(?:name|title)\s+[\"']?([^\"']+?)[\"']?\s+in\s+(?:it|them)\b",
        # "songs with goat in the name/title"
        r"\b(?:songs?|tracks?)\s+(?:that\s+)?(?:have|has|with|containing|including)\s+[\"']?([^\"']+?)[\"']?\s+in\s+(?:their\s+|the\s+)?(?:name|title)s?\b",
        # "title/name contains goat"
        r"\b(?:name|title)s?\s+(?:that\s+)?(?:contain|contains|include|includes|with)\s+(?:the\s+word\s+)?[\"']?([^\"',;]+?)[\"']?(?:\s|$)",
    )

    term = ""
    lower = text.casefold()
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            term = _clean_term(match.group(1))
            break

    # A common conversational construction: "find me songs with the name goat in them"
    if not term:
        match = re.search(
            r"\b(?:name|title)\s+[\"']?([\w-]+(?:\s+[\w-]+){0,2})[\"']?\s+in\s+(?:it|them)\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            term = _clean_term(match.group(1))

    if not term or len(term) > 60:
        return None

    # Trim trailing preference language accidentally captured by permissive wording.
    term = re.split(r"\s*,?\s*\b(?:ideally|preferably|especially|mostly|but|and\s+ideally)\b", term, maxsplit=1, flags=re.IGNORECASE)[0]
    term = _clean_term(term)
    if not term:
        return None

    required = bool(
        re.search(r"\b(?:find|give|show|make|songs?|tracks?)\b", lower)
        and re.search(r"\b(?:name|title|in them|in it)\b", lower)
    ) or bool(re.search(r"\b(?:must|only|need to|have to)\b", lower))

    return {
        "term": term,
        "normalized": _normalize(term),
        "required": required,
        "heavy_preference": any(word in lower for word in HEAVY_TERMS),
    }


def has_title_constraint(prompt: str) -> bool:
    return title_constraint(prompt) is not None


def _load_matching_local_tracks(database_path: Path, needle: str) -> list[dict]:
    if not database_path.is_file() or not needle:
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

    seen = set()
    result = []
    for row in rows:
        title_norm = _normalize(row["title"])
        if needle not in title_norm:
            continue
        key = (_normalize(row["artist"]), title_norm)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "artist": row["artist"],
            "title": row["title"],
            "genre": row["genre"] or "",
            "source": "local-title-match",
        })
    return result


def _heavy_score(track: dict) -> int:
    genre = _normalize(track.get("genre", ""))
    return sum(1 for term in HEAVY_GENRE_TERMS if term in genre)


def apply_request_constraints(
    prompt: str,
    generated: dict,
    database_path: Path,
    *,
    track_limit: int = 20,
    artist_limit: int = 2,
) -> dict:
    """Enforce literal title constraints without treating matches as style anchors."""
    intent = title_constraint(prompt)
    if not intent:
        return generated

    needle = intent["normalized"]
    selected = list(generated.get("tracks") or [])
    matching_selected = [
        track for track in selected
        if needle in _normalize(track.get("title", ""))
    ]

    local_matches = _load_matching_local_tracks(database_path, needle)
    if intent["heavy_preference"]:
        local_matches.sort(key=lambda track: (-_heavy_score(track), _normalize(track["artist"]), _normalize(track["title"])))

    # For a required title query, unrelated tracks are not useful filler. For a
    # preference-only query, keep the model's broader sequence after title matches.
    pool = []
    seen = set()
    artist_counts: dict[str, int] = {}

    def add(track: dict) -> None:
        if len(pool) >= track_limit:
            return
        artist = _normalize(track.get("artist", ""))
        title = _normalize(track.get("title", ""))
        if not artist or not title or (artist, title) in seen:
            return
        if artist_counts.get(artist, 0) >= artist_limit:
            return
        seen.add((artist, title))
        artist_counts[artist] = artist_counts.get(artist, 0) + 1
        pool.append({
            "artist": track.get("artist", ""),
            "title": track.get("title", ""),
            "source": track.get("source", "local"),
        })

    # Heavy local matches first when heaviness was explicitly requested; otherwise
    # preserve the curator's matching order first.
    if intent["heavy_preference"]:
        for track in local_matches:
            if _heavy_score(track) > 0:
                add(track)
        for track in matching_selected:
            add(track)
        for track in local_matches:
            add(track)
    else:
        for track in matching_selected:
            add(track)
        for track in local_matches:
            add(track)

    if not intent["required"]:
        for track in selected:
            add(track)

    # If nothing matched at all, retain the model result rather than silently
    # producing an empty playlist; the log makes the miss visible for debugging.
    if pool:
        generated["tracks"] = pool
    else:
        print(
            f"[Tune Raider] title constraint '{intent['term']}' produced no matching local or curated tracks; keeping curator output",
            flush=True,
        )

    qualifier = "leaning toward heavier picks where possible" if intent["heavy_preference"] else "using the title match as the selection rule"
    generated["description"] = f"Tracks with '{intent['term']}' in the title, {qualifier}."
    generated["name"] = f"{intent['term'].title()} in the Title"

    print(
        f"[Tune Raider] enforced title constraint: {intent['term']} | required={intent['required']} | selected={len(generated.get('tracks') or [])}",
        flush=True,
    )
    return generated
