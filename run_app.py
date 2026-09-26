#!/usr/bin/env python3
"""Tune Raider application entrypoint with post-curation safeguards."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests
from flask import jsonify, request

import app as tone_raider
from anchor_policy import ensure_prompt_anchor
from intent_policy import apply_request_constraints, has_title_constraint, title_constraint
from spotify_discovery import search_broad_context


MIN_PLAYLIST_TRACKS = max(1, int(os.environ.get("MIN_PLAYLIST_TRACKS", "10")))
MAX_REFINEMENT_TRACKS = max(MIN_PLAYLIST_TRACKS, int(os.environ.get("MAX_REFINEMENT_TRACKS", "40")))

REFINEMENT_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "remove_indexes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
        },
        "addition_prompt": {"type": "string"},
        "target_count": {"type": "integer", "minimum": 1, "maximum": MAX_REFINEMENT_TRACKS},
        "name": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["remove_indexes", "addition_prompt", "target_count", "name", "description"],
    "additionalProperties": False,
}

_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist
_original_create_from_prompt = tone_raider.create_from_prompt
_original_home = tone_raider.app.view_functions.get("home")


def _excluded_keys(excluded_tracks) -> set[tuple[str, str]]:
    result = set()
    for value in excluded_tracks or []:
        artist, separator, title = str(value).partition(" - ")
        if separator:
            result.add((tone_raider.spotify.normalize(artist), tone_raider.spotify.normalize(title)))
    return result


def _merge_tracks(base: list[dict], additions: list[dict], limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    artist_counts: dict[str, int] = {}

    def add(track: dict, *, enforce_artist_cap: bool = True) -> None:
        if len(merged) >= limit:
            return
        artist = str(track.get("artist") or "").strip()
        title = str(track.get("title") or "").strip()
        artist_key = tone_raider.spotify.normalize(artist)
        title_key = tone_raider.spotify.normalize(title)
        key = (artist_key, title_key)
        if not artist_key or not title_key or key in seen:
            return
        if enforce_artist_cap and artist_counts.get(artist_key, 0) >= tone_raider.PLAYLIST_ARTIST_LIMIT:
            return
        seen.add(key)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        merged.append({
            "artist": artist,
            "title": title,
            "source": str(track.get("source") or "curated"),
        })

    for track in base:
        add(track, enforce_artist_cap=False)
    for track in additions:
        add(track, enforce_artist_cap=True)
    return merged


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

    for track in selected:
        add(track.get("artist", ""), track.get("title", ""), str(track.get("source") or "curated-title-match"))

    for track in discovered:
        artists = track.get("artists") or []
        primary_artist = str((artists[0] if artists else {}).get("name") or "").strip()
        add(primary_artist, track.get("name", ""), "spotify-title-search")
        if len(merged) >= tone_raider.PLAYLIST_TRACK_LIMIT:
            break

    exact_count = len(merged)
    broad_count = 0
    if len(merged) < MIN_PLAYLIST_TRACKS:
        broader = search_broad_context(
            token,
            intent["term"],
            heavy_preference=bool(intent.get("heavy_preference")),
            limit=max(50, MIN_PLAYLIST_TRACKS * 4),
        )
        before = len(merged)
        for track in broader:
            artists = track.get("artists") or []
            primary_artist = str((artists[0] if artists else {}).get("name") or "").strip()
            add(primary_artist, track.get("name", ""), "spotify-broad-fallback")
            if len(merged) >= max(MIN_PLAYLIST_TRACKS, tone_raider.PLAYLIST_TRACK_LIMIT):
                break
        broad_count = len(merged) - before
        if broad_count:
            generated["description"] = (
                f"Only {exact_count} tracks with '{intent['term']}' in the title were found; "
                f"the rest use a broader {'heavy-music ' if intent.get('heavy_preference') else ''}search to fill the playlist."
            )

    if merged:
        generated["tracks"] = merged

    print(
        f"[Tune Raider] Spotify title discovery: '{intent['term']}' -> {len(discovered)} exact candidates, "
        f"{exact_count} exact/curated selected, {broad_count} broader fallback, {len(merged)} total",
        flush=True,
    )
    return generated


def _broaden_sparse_general_result(prompt: str, generated: dict, excluded_tracks=None) -> dict:
    if len(generated.get("tracks") or []) >= MIN_PLAYLIST_TRACKS:
        return generated

    existing = list(generated.get("tracks") or [])
    exclude = list(excluded_tracks or []) + [
        f"{track.get('artist', '')} - {track.get('title', '')}" for track in existing
    ]
    broader_prompt = (
        f"{prompt}\n\nThe first pass found very few usable tracks. Broaden the search while preserving the core intent. "
        "Use musically adjacent artists, neighboring subgenres, and reasonable stylistic interpretations rather than unrelated filler."
    )
    try:
        broader = _original_ask_for_hybrid_playlist(broader_prompt, exclude)
    except Exception as exc:
        print(f"[Tune Raider] broader fallback failed: {exc}", flush=True)
        return generated

    merged = _merge_tracks(existing, list(broader.get("tracks") or []), tone_raider.PLAYLIST_TRACK_LIMIT)
    if merged:
        generated["tracks"] = merged
    print(
        f"[Tune Raider] sparse-result fallback: {len(existing)} -> {len(merged)} tracks",
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
        generated = _broaden_sparse_general_result(prompt, generated, excluded_tracks)
    return generated


tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_safeguards


def create_from_prompt_with_notice(prompt: str, excluded_tracks=None) -> dict:
    result = _original_create_from_prompt(prompt, excluded_tracks)
    if len(result.get("tracks") or []) < MIN_PLAYLIST_TRACKS:
        result["notice"] = (
            f"Only {len(result.get('tracks') or [])} tracks could be confidently found and resolved after Tune Raider broadened the search. "
            f"The playlist was still created rather than adding unrelated filler just to reach the {MIN_PLAYLIST_TRACKS}-track minimum."
        )
    return result


tone_raider.create_from_prompt = create_from_prompt_with_notice


def _save_refined_playlist(
    source_row,
    instruction: str,
    requested_tracks: list[dict],
    name: str,
    description: str,
    target_count: int,
) -> dict:
    token = tone_raider.spotify.get_access_token()
    resolved = []
    missing = []
    seen_uris = set()
    for requested_track in requested_tracks:
        track_request = tone_raider.spotify.TrackRequest(
            str(requested_track.get("artist") or ""),
            str(requested_track.get("title") or ""),
        )
        track = tone_raider.spotify.search_track(token, track_request)
        if track and track.get("uri") not in seen_uris:
            resolved.append(track)
            seen_uris.add(track["uri"])
        elif not track:
            missing.append(f"{track_request.artist} - {track_request.title}")

    if not resolved:
        raise tone_raider.AppError("Spotify could not resolve any tracks for the refined playlist.")

    playlist = tone_raider.spotify.create_playlist(token, name=name, description=description, public=False)
    tone_raider.spotify.add_items(token, playlist["id"], [track["uri"] for track in resolved])
    tracks = [
        {
            "artist": ", ".join(artist["name"] for artist in track.get("artists", [])),
            "title": track["name"],
            "url": track.get("external_urls", {}).get("spotify"),
        }
        for track in resolved
    ]
    prompt = f"Refine {source_row['name']}: {instruction}"
    result = {
        "prompt": prompt,
        "name": playlist.get("name", name),
        "description": description,
        "tracks": tracks,
        "spotify_url": playlist.get("external_urls", {}).get("spotify"),
        "missing": missing,
        "source": "hybrid",
        "source_tracks": requested_tracks,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if len(tracks) < target_count:
        result["notice"] = (
            f"The refinement targeted {target_count} tracks, but only {len(tracks)} could be confidently resolved on Spotify. "
            "The revised playlist was still created with the usable matches."
        )

    with tone_raider.database() as connection:
        cursor = connection.execute(
            "INSERT INTO generated_playlists (prompt, name, description, tracks, spotify_url, created_at, source, source_tracks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result["prompt"], result["name"], result["description"], json.dumps(tracks),
                result["spotify_url"], result["created_at"], result["source"], json.dumps(requested_tracks),
            ),
        )
        result["id"] = cursor.lastrowid
    return result


def _refine_playlist(row, instruction: str) -> dict:
    current = json.loads(row["source_tracks"]) or json.loads(row["tracks"])
    if not current:
        raise tone_raider.AppError("That history item has no tracks to refine.")

    numbered = [
        {"index": index, "artist": track.get("artist", ""), "title": track.get("title", "")}
        for index, track in enumerate(current, 1)
    ]
    plan = tone_raider.model_json(
        "Revise an existing playlist according to the user's edit request. "
        "Return remove_indexes only for tracks the request clearly asks to remove or replace. "
        "Use addition_prompt to describe tracks that should be discovered and added; leave it empty when no additions are needed. "
        "target_count is the desired final number of tracks: preserve the current count unless the user explicitly asks to add/remove a quantity or otherwise change the size. "
        "Preserve unaffected tracks and their order. Create a concise revised playlist name and one-sentence description. "
        "Existing playlist: " + json.dumps({
            "name": row["name"],
            "description": row["description"],
            "original_prompt": row["prompt"],
            "tracks": numbered,
        }),
        instruction,
        REFINEMENT_PLAN_SCHEMA,
        stage="playlist refinement",
    )

    remove_indexes = {
        int(value) for value in plan.get("remove_indexes", [])
        if isinstance(value, int) and 1 <= value <= len(current)
    }
    remaining = [track for index, track in enumerate(current, 1) if index not in remove_indexes]
    target_count = max(1, min(int(plan.get("target_count") or len(remaining) or 1), MAX_REFINEMENT_TRACKS))
    addition_prompt = str(plan.get("addition_prompt") or "").strip()

    additions = []
    if addition_prompt or target_count > len(remaining):
        discovery_prompt = addition_prompt or instruction
        excluded = [f"{track.get('artist', '')} - {track.get('title', '')}" for track in current]
        generated = tone_raider.ask_for_hybrid_playlist(discovery_prompt, excluded)
        additions = list(generated.get("tracks") or [])

    final_tracks = _merge_tracks(remaining, additions, target_count)
    if len(final_tracks) < target_count and additions:
        excluded = [f"{track.get('artist', '')} - {track.get('title', '')}" for track in final_tracks]
        broad = _original_ask_for_hybrid_playlist(
            f"{addition_prompt or instruction}\nBroaden this slightly with musically adjacent choices to fill the remaining playlist slots.",
            excluded,
        )
        final_tracks = _merge_tracks(final_tracks, list(broad.get("tracks") or []), target_count)

    name = str(plan.get("name") or f"{row['name']} · Refined").strip()
    description = str(plan.get("description") or row["description"] or tone_raider.spotify.DEFAULT_DESCRIPTION).strip()
    return _save_refined_playlist(row, instruction, final_tracks, name, description, target_count)


@tone_raider.app.post("/api/history/<int:playlist_id>/refine")
def refine_history_item(playlist_id: int):
    body = request.get_json(silent=True) or {}
    instruction = str(body.get("instruction") or "").strip()
    if not instruction:
        return jsonify({"error": "Describe what you want to change about the playlist."}), 400

    with tone_raider.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404

    try:
        return jsonify(_refine_playlist(row, instruction))
    except (tone_raider.AppError, tone_raider.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


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


def _home_with_history_controls():
    html = _original_home() if _original_home else ""
    if isinstance(html, str) and "history_controls.js" not in html:
        html = html.replace(
            "</head>",
            '<script defer src="/static/history_controls.js"></script>\n</head>',
            1,
        )
    return html


if _original_home:
    tone_raider.app.view_functions["home"] = _home_with_history_controls


if __name__ == "__main__":
    tone_raider.app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
