"""Append fresh discoveries to a playlist that is already working."""
from __future__ import annotations

import json
import os

import requests
from flask import jsonify, request

import refinement_context
import run_app
from learning_store import record
from preference_policy import artist_blocked
from spotify_playlist_state import (
    as_exclusions,
    compare_stored_to_live,
    ensure_playlist_read_scope,
    fetch_playlist_tracks,
)

tr = run_app.tone_raider
ADD_TO_COUNT = max(1, min(20, int(os.environ.get("DISCOVERY_ADD_TO_COUNT", "5"))))


def _root_prompt(row) -> str:
    return refinement_context._root_prompt(row) or str(row["prompt"] or "").strip()


def _addition_prompt(row, live: list[dict], manual_removed: list[dict], *, refill: bool = False) -> str:
    specimens = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in live[:20]
        if track.get("artist") and track.get("title")
    ]
    removed = as_exclusions(manual_removed)
    parts = [
        _root_prompt(row),
        "The current Spotify playlist is working. Add more music to it rather than rebuilding or changing direction.",
        "Treat the tracks still in the playlist as positive style specimens. Find new tracks that extend the same musical idea with useful variety while remaining faithful to the original source artist/song, genre, instrumentation, rhythmic feel, production language, and requested energy.",
    ]
    if row["description"]:
        parts.append(f"Current playlist description: {row['description']}")
    if specimens:
        parts.append("Current successful playlist tracks: " + "; ".join(specimens))
    if removed:
        parts.append("The user manually removed these tracks. Never add these exact tracks back during this addition: " + "; ".join(removed))
    parts.append(
        f"Return enough strong candidates to append {ADD_TO_COUNT} genuinely new tracks. Do not repeat anything already in the playlist. Favor artist variety except for an explicitly named inspiration artist, which may contribute a few strong tracks."
    )
    if refill:
        parts.append("Some first-pass candidates failed Spotify resolution. Find alternate tracks inside the same sound; do not broaden genre to fill the quota.")
    return "\n".join(part for part in parts if part)


def _resolve_new(token: str, requested: list[dict], live_uris: set[str], limit: int) -> tuple[list[dict], list[str]]:
    resolved: list[dict] = []
    missing: list[str] = []
    seen = set(live_uris)
    for item in requested:
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        if not artist or not title or artist_blocked(artist):
            continue
        track = tr.spotify.search_track(token, tr.spotify.TrackRequest(artist, title))
        if track and track.get("uri") and track["uri"] not in seen:
            resolved.append(track)
            seen.add(track["uri"])
            if len(resolved) >= limit:
                break
        elif not track:
            missing.append(f"{artist} - {title}")
    return resolved, missing


def add_to_playlist(playlist_id: int):
    body = request.get_json(silent=True) or {}
    requested_count = body.get("count")
    count = ADD_TO_COUNT
    if isinstance(requested_count, int):
        count = max(1, min(20, requested_count))

    with tr.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404

    try:
        ensure_playlist_read_scope(tr.spotify)
        token = tr.spotify.get_access_token()
        spotify_playlist_id, live = fetch_playlist_tracks(tr.spotify, token, row["spotify_url"])
        stored = json.loads(row["tracks"]) or json.loads(row["source_tracks"]) or []
        manual_removed, manual_added = compare_stored_to_live(tr.spotify, stored, live)

        if manual_removed or manual_added:
            record(
                tr.database,
                "spotify_manual_edit_observed",
                parent_playlist_id=row["id"],
                prompt=_root_prompt(row),
                payload={"removed_tracks": manual_removed, "added_tracks": manual_added, "observed_before": "add_to"},
            )

        excluded = as_exclusions(live + manual_removed)
        prompt = _addition_prompt(row, live, manual_removed)
        generated = tr.ask_for_hybrid_playlist(prompt, excluded)
        live_uris = {str(track.get("uri") or "") for track in live if track.get("uri")}
        resolved, missing = _resolve_new(token, list(generated.get("tracks") or []), live_uris, count)

        if len(resolved) < count:
            refill_excluded = excluded + [
                f"{', '.join(a.get('name', '') for a in track.get('artists', []))} - {track.get('name', '')}"
                for track in resolved
            ]
            refill = tr.ask_for_hybrid_playlist(_addition_prompt(row, live, manual_removed, refill=True), refill_excluded)
            more, more_missing = _resolve_new(token, list(refill.get("tracks") or []), live_uris | {t["uri"] for t in resolved}, count - len(resolved))
            resolved.extend(more)
            missing.extend(more_missing)

        if not resolved:
            raise tr.AppError("No additional tracks could be resolved without repeating the current playlist.")

        tr.spotify.add_items(token, spotify_playlist_id, [track["uri"] for track in resolved])
        added = [
            {
                "artist": ", ".join(artist.get("name", "") for artist in track.get("artists", [])),
                "title": track.get("name", ""),
                "url": (track.get("external_urls") or {}).get("spotify"),
                "uri": track.get("uri"),
            }
            for track in resolved
        ]
        updated = live + added
        stored_tracks = [
            {"artist": track.get("artist", ""), "title": track.get("title", ""), "url": track.get("url")}
            for track in updated
        ]
        source_tracks = [
            {"artist": track.get("artist", ""), "title": track.get("title", ""), "source": "spotify-live" if index < len(live) else "spotify-add-to"}
            for index, track in enumerate(updated)
        ]
        with tr.database() as connection:
            connection.execute(
                "UPDATE generated_playlists SET tracks = ?, source_tracks = ? WHERE id = ?",
                (json.dumps(stored_tracks), json.dumps(source_tracks), row["id"]),
            )

        record(
            tr.database,
            "add_to",
            playlist_id=row["id"],
            parent_playlist_id=row["id"],
            prompt=_root_prompt(row),
            payload={
                "requested_count": count,
                "added_tracks": added,
                "manual_removed_tracks": manual_removed,
                "manual_added_tracks": manual_added,
                "interpretation": "current_playlist_positive_specimen",
            },
        )
        print(
            f"[Tune Raider] add to: {len(live)} live + {len(added)} new; {len(manual_removed)} manual removals excluded",
            flush=True,
        )
        return jsonify({
            "added": len(added),
            "tracks": added,
            "playlist_id": row["id"],
            "spotify_url": row["spotify_url"],
            "missing": missing,
            "notice": "" if len(added) >= count else f"Added {len(added)} of {count} requested tracks without loosening the playlist's sound.",
        })
    except (tr.AppError, tr.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


tr.app.add_url_rule("/api/history/<int:playlist_id>/add", endpoint="add_to_playlist", view_func=add_to_playlist, methods=["POST"])
