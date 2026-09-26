"""Artist-specific metadata for Tune Raider's prompt idea generator.

This wraps the existing /api/prompt-profile endpoint instead of replacing its
Spotify sampling logic. It merges local genres/audio measurements, adds a small
amount of Last.fm neighborhood context, and opportunistically uses MusicBrainz
without making page load wait on dozens of rate-limited requests.
"""
from __future__ import annotations

from collections import defaultdict

import requests
from flask import jsonify

import app as tone_raider
import lastfm_client as lastfm
import musicbrainz_client as musicbrainz
from audio.library_context import Library

_original_prompt_profile = tone_raider.app.view_functions.get("prompt_profile")
_original_home = tone_raider.app.view_functions.get("home")


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _append_unique(target: list[str], values, *, limit: int = 10) -> None:
    seen = {_norm(value) for value in target}
    for value in values or []:
        text = str(value or "").strip()
        key = _norm(text)
        if not text or not key or key in seen:
            continue
        target.append(text)
        seen.add(key)
        if len(target) >= limit:
            break


def _unwrap_response(result):
    status = 200
    response = result
    if isinstance(result, tuple):
        response = result[0]
        if len(result) > 1 and isinstance(result[1], int):
            status = result[1]
    data = response.get_json(silent=True) if hasattr(response, "get_json") else None
    return response, status, data


def _local_artist_context() -> dict[str, dict]:
    try:
        library = Library(tone_raider.AUDIO_DATABASE)
    except Exception:
        return {}

    rows_by_artist: dict[str, list[dict]] = defaultdict(list)
    for row in library.rows:
        rows_by_artist[_norm(row.get("artist"))].append(row)

    result = {}
    for artist_key, rows in rows_by_artist.items():
        genres: list[str] = []
        for row in rows:
            _append_unique(genres, [row.get("genre")], limit=8)

        axis_values: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            for axis, value in (row.get("profile") or {}).items():
                if isinstance(value, (int, float)):
                    axis_values[axis].append(float(value))
        sound = {
            axis: round(sum(values) / len(values))
            for axis, values in axis_values.items()
            if values
        }
        result[artist_key] = {
            "genres": genres,
            "sound_profile": sound,
            "local_track_count": len(rows),
        }
    return result


def enhanced_prompt_profile():
    if not _original_prompt_profile:
        return jsonify({"artists": [], "genres": [], "profiles": []}), 503

    original = _original_prompt_profile()
    response, status, data = _unwrap_response(original)
    if status != 200 or not isinstance(data, dict):
        return original

    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return original

    local_context = _local_artist_context()

    # Keep the idea endpoint quick. Last.fm can cheaply enrich a useful subset;
    # MusicBrainz is deliberately limited because its public API is rate-limited.
    lastfm_budget = 10
    musicbrainz_budget = 2

    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        name = str(profile.get("name") or "").strip()
        if not name:
            continue

        genres = [str(value).strip() for value in profile.get("genres") or [] if str(value).strip()]
        local = local_context.get(_norm(name), {})
        _append_unique(genres, local.get("genres"), limit=10)
        profile["genres"] = genres
        profile["sound_profile"] = dict(local.get("sound_profile") or {})
        profile["local_track_count"] = int(local.get("local_track_count") or 0)

        similar: list[str] = []
        if lastfm.API_KEY and index < lastfm_budget:
            try:
                for item in lastfm.similar_artists(name, limit=5):
                    if float(item.get("match") or 0) >= 0.12:
                        similar.append(str(item.get("name") or "").strip())
            except (requests.RequestException, RuntimeError, ValueError):
                pass
        profile["similar_artists"] = [value for value in similar if value][:4]

        mb_tags: list[str] = []
        mb_related: list[str] = []
        if musicbrainz.ENABLED and index < musicbrainz_budget:
            try:
                mb_tags = [tag["name"] for tag in musicbrainz.artist_tags(name, limit=5)]
                mb_related = musicbrainz.related_artists(name, limit=4)
            except (requests.RequestException, RuntimeError, ValueError):
                pass
        profile["musicbrainz_tags"] = mb_tags
        _append_unique(profile["genres"], mb_tags, limit=10)
        _append_unique(profile["similar_artists"], mb_related, limit=6)

        sources = [str(profile.get("genre_source") or "").strip()]
        if local.get("genres") or local.get("sound_profile"):
            sources.append("local")
        if similar:
            sources.append("lastfm-similarity")
        if mb_tags or mb_related:
            sources.append("musicbrainz")
        profile["context_sources"] = [value for value in dict.fromkeys(sources) if value]

    genre_counts: dict[str, int] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for genre in profile.get("genres") or []:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1

    data["genres"] = [genre for genre, _ in sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:16]]
    data["source"] = "liked-songs+lastfm+local+musicbrainz"
    return jsonify(data)


def home_with_richer_prompt_ideas():
    html = _original_home() if _original_home else ""
    if isinstance(html, str) and "prompt_ideas.js" not in html:
        html = html.replace(
            "</body>",
            '<script src="/static/prompt_ideas.js"></script>\n</body>',
            1,
        )
    return html


if _original_prompt_profile:
    tone_raider.app.view_functions["prompt_profile"] = enhanced_prompt_profile
if _original_home:
    tone_raider.app.view_functions["home"] = home_with_richer_prompt_ideas
