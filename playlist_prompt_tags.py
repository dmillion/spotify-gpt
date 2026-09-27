"""Resolve saved-playlist tags embedded in Tune Raider prompts."""
from __future__ import annotations

import json
import re

from flask import jsonify

import run_app

tr = run_app.tone_raider
_original_ask = tr.ask_for_hybrid_playlist

# Readable textarea tag. Example: @[Riverboat Soul Party]
TAG_RE = re.compile(r"@\[(?P<name>[^\]]+)\](?:\(playlist:(?P<id>\d+)\))?")


def _stored_tracks(row) -> list[dict]:
    try:
        return json.loads(row["source_tracks"]) or json.loads(row["tracks"]) or []
    except (TypeError, ValueError, KeyError):
        return []


def _live_tracks(row) -> list[dict]:
    spotify_url = str(row["spotify_url"] or "").strip()
    if not spotify_url:
        return []
    try:
        import spotify_playlist_state as playlist_state
        token_info = tr.spotify.load_token()
        if not token_info or not tr.spotify.token_has_required_scopes(token_info):
            return []
        token = str(token_info.get("access_token") or "").strip()
        if not token:
            return []
        _playlist_id, tracks = playlist_state.fetch_playlist_tracks(tr.spotify, token, spotify_url)
        return tracks
    except Exception:
        return []


def _row_for_tag(name: str, playlist_id: str | None):
    with tr.database() as connection:
        if playlist_id:
            return connection.execute(
                "SELECT * FROM generated_playlists WHERE id = ?", (int(playlist_id),)
            ).fetchone()
        return connection.execute(
            "SELECT * FROM generated_playlists WHERE name = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()


def _playlist_context(row, display_name: str) -> str | None:
    if not row:
        return None
    tracks = _live_tracks(row) or _stored_tracks(row)
    track_lines = [
        f"- {str(track.get('artist') or '').strip()} - {str(track.get('title') or '').strip()}"
        for track in tracks[:40]
        if track.get("artist") and track.get("title")
    ]
    name = str(row["name"] or display_name).strip()
    parts = [f"Referenced saved playlist: {name}"]
    if row["description"]:
        parts.append(f"Playlist description: {row['description']}")
    if row["prompt"]:
        parts.append(f"Original playlist prompt: {row['prompt']}")
    if track_lines:
        parts.append("Current playlist tracks:\n" + "\n".join(track_lines))
    parts.append(
        "Use this playlist as musical reference/specimen data according to the user's wording. "
        "Do not assume its tracks must be repeated, and do not let it override an explicit new artist, genre, mood, or direction."
    )
    return "\n".join(parts)


def expand_playlist_tags(prompt: str) -> str:
    text = str(prompt or "")
    matches = list(TAG_RE.finditer(text))
    if not matches:
        return text

    contexts = []
    seen = set()
    for match in matches:
        row = _row_for_tag(match.group("name"), match.group("id"))
        if not row or row["id"] in seen:
            continue
        seen.add(row["id"])
        context = _playlist_context(row, match.group("name"))
        if context:
            contexts.append(context)

    cleaned = TAG_RE.sub(lambda m: f"the saved playlist {m.group('name')}", text)
    if not contexts:
        return cleaned

    print(f"[Tune Raider] prompt references {len(contexts)} saved playlist(s): {sorted(seen)}", flush=True)
    return cleaned + "\n\nSAVED PLAYLIST REFERENCE CONTEXT\n" + "\n\n".join(contexts)


def ask_with_playlist_tags(prompt: str, excluded_tracks=None) -> dict:
    return _original_ask(expand_playlist_tags(prompt), excluded_tracks)


@tr.app.get("/api/prompt-playlists")
def prompt_playlists():
    with tr.database() as connection:
        rows = connection.execute(
            "SELECT id, name, description, created_at, tracks FROM generated_playlists ORDER BY id DESC"
        ).fetchall()
    result = []
    for row in rows:
        try:
            track_count = len(json.loads(row["tracks"]) or [])
        except (TypeError, ValueError):
            track_count = 0
        result.append({
            "id": row["id"], "name": row["name"], "description": row["description"],
            "created_at": row["created_at"], "track_count": track_count,
        })
    return jsonify(result)


tr.ask_for_hybrid_playlist = ask_with_playlist_tags
