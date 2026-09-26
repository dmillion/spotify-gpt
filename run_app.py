#!/usr/bin/env python3
"""Tune Raider application entrypoint with post-curation safeguards."""
from __future__ import annotations

import os

from flask import jsonify

import app as tone_raider
from anchor_policy import ensure_prompt_anchor
from intent_policy import apply_request_constraints, has_title_constraint, title_constraint


_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist


def _excluded_keys(excluded_tracks) -> set[tuple[str, str]]:
    result = set()
    for value in excluded_tracks or []:
        artist, separator, title = str(value).partition(" - ")
        if separator:
            result.add((tone_raider.spotify.normalize(artist), tone_raider.spotify.normalize(title)))
    return result


def _supplement_title_query_from_spotify(prompt: str, generated: dict, excluded_tracks=None) -> dict:
    """Broaden literal title searches beyond the bounded local/Last.fm curator pool."""
    intent = title_constraint(prompt)
    if not intent:
        return generated

    token = tone_raider.spotify.get_access_token()
    discovered = tone_raider.spotify.search_tracks_by_title_term(
        token,
        intent["term"],
        heavy_preference=bool(intent.get("heavy_preference")),
        limit=max(50, tone_raider.PLAYLIST_TRACK_LIMIT * 3),
    )

    selected = list(generated.get("tracks") or [])
    excluded = _excluded_keys(excluded_tracks)
    merged = []
    seen = set()
    artist_counts: dict[str, int] = {}

    def add(artist: str, title: str, source: str) -> None:
        if len(merged) >= tone_raider.PLAYLIST_TRACK_LIMIT:
            return
        artist = str(artist or "").strip()
        title = str(title or "").strip()
        artist_key = tone_raider.spotify.normalize(artist)
        title_key = tone_raider.spotify.normalize(title)
        key = (artist_key, title_key)
        if not artist_key or not title_key or key in seen or key in excluded:
            return
        if artist_counts.get(artist_key, 0) >= tone_raider.PLAYLIST_ARTIST_LIMIT:
            return
        seen.add(key)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        merged.append({"artist": artist, "title": title, "source": source})

    # Keep heavy local/library matches already selected by intent_policy first.
    for track in selected:
        add(track.get("artist", ""), track.get("title", ""), str(track.get("source") or "curated-title-match"))

    for track in discovered:
        artists = track.get("artists") or []
        primary_artist = str((artists[0] if artists else {}).get("name") or "").strip()
        add(primary_artist, track.get("name", ""), "spotify-title-search")
        if len(merged) >= tone_raider.PLAYLIST_TRACK_LIMIT:
            break

    if merged:
        generated["tracks"] = merged

    print(
        f"[Tune Raider] Spotify title discovery: '{intent['term']}' -> {len(discovered)} matches, {len(merged)} selected",
        flush=True,
    )
    return generated


def ask_for_hybrid_playlist_with_safeguards(prompt: str, excluded_tracks=None) -> dict:
    generated = _original_ask_for_hybrid_playlist(prompt, excluded_tracks)
    generated = apply_request_constraints(
        prompt,
        generated,
        tone_raider.AUDIO_DATABASE,
        track_limit=tone_raider.PLAYLIST_TRACK_LIMIT,
        artist_limit=tone_raider.PLAYLIST_ARTIST_LIMIT,
    )

    # Literal title/name searches are constraint queries, not artist-inspiration
    # prompts. Broaden them with Spotify title search, then skip anchor inference so
    # a word such as "goat" cannot become an accidental artist named Goat anchor.
    if has_title_constraint(prompt):
        generated = _supplement_title_query_from_spotify(prompt, generated, excluded_tracks)
    else:
        generated = ensure_prompt_anchor(
            prompt,
            generated,
            tone_raider.AUDIO_DATABASE,
            excluded_tracks=excluded_tracks,
            track_limit=tone_raider.PLAYLIST_TRACK_LIMIT,
            artist_limit=tone_raider.PLAYLIST_ARTIST_LIMIT,
        )
    return generated


tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_safeguards


@tone_raider.app.delete("/api/history/<int:playlist_id>")
def delete_history_item(playlist_id: int):
    """Remove one generated playlist from local Tune Raider history only."""
    with tone_raider.database() as connection:
        cursor = connection.execute(
            "DELETE FROM generated_playlists WHERE id = ?",
            (playlist_id,),
        )
    if cursor.rowcount == 0:
        return jsonify({"error": "That playlist is no longer in local history."}), 404
    return jsonify({"deleted": True, "id": playlist_id})


@tone_raider.app.delete("/api/history")
def clear_history():
    """Clear generated-playlist history without touching Spotify playlists."""
    with tone_raider.database() as connection:
        count = connection.execute("SELECT COUNT(*) FROM generated_playlists").fetchone()[0]
        connection.execute("DELETE FROM generated_playlists")
    return jsonify({"deleted": int(count)})


if __name__ == "__main__":
    tone_raider.app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
