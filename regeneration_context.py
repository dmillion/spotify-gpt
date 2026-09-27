"""Fresh regeneration with Spotify-resolution backfill."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests
from flask import jsonify

import run_app
from learning_store import record
from preference_policy import artist_blocked

tr = run_app.tone_raider


def _fresh_prompt(row, *, refill: bool = False) -> str:
    """Rerun the saved prompt without treating the prior playlist as positive context."""
    prompt = str(row["prompt"] or "").strip()
    if not refill:
        return prompt
    return (
        prompt
        + "\n\nThis is a fresh retry of the same request because some candidates failed Spotify resolution. "
          "Find additional tracks that independently satisfy the ORIGINAL prompt. Do not use the previous playlist as style evidence "
          "and do not broaden the requested genre/sound merely to fill space."
    )


def _resolve(token: str, requested: list[dict], *, seen_uris=None) -> tuple[list[dict], list[str]]:
    seen_uris = seen_uris if seen_uris is not None else set()
    resolved = []
    missing = []
    for item in requested:
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        if not artist or not title or artist_blocked(artist):
            continue
        req = tr.spotify.TrackRequest(artist, title)
        track = tr.spotify.search_track(token, req)
        if track and track.get("uri") and track["uri"] not in seen_uris:
            resolved.append(track)
            seen_uris.add(track["uri"])
        elif not track:
            missing.append(f"{artist} - {title}")
    return resolved, missing


def regenerate_contextual(playlist_id: int):
    with tr.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404

    previous_source = json.loads(row["source_tracks"]) or []
    previous_resolved = json.loads(row["tracks"]) or []
    previous = previous_source or previous_resolved
    excluded = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in previous
        if track.get("artist") and track.get("title")
    ]
    target_count = min(
        tr.PLAYLIST_TRACK_LIMIT,
        max(run_app.MIN_PLAYLIST_TRACKS, len(previous_resolved), len(previous_source)),
    )

    try:
        # Same saved prompt, same complete discovery pipeline, fresh candidate draw.
        # Previous tracks are only exact-track exclusions so Regenerate behaves like
        # "try this prompt again", while Refine remains the iterative/contextual action.
        generated = tr.ask_for_hybrid_playlist(_fresh_prompt(row), excluded)
        requested = list(generated.get("tracks") or [])

        token = tr.spotify.get_access_token()
        seen_uris: set[str] = set()
        resolved, missing = _resolve(token, requested, seen_uris=seen_uris)

        if len(resolved) < target_count:
            refill_excluded = excluded + [
                f"{', '.join(a['name'] for a in track.get('artists', []))} - {track.get('name', '')}"
                for track in resolved
            ]
            refill = tr.ask_for_hybrid_playlist(_fresh_prompt(row, refill=True), refill_excluded)
            extra_resolved, extra_missing = _resolve(
                token,
                list(refill.get("tracks") or []),
                seen_uris=seen_uris,
            )
            resolved.extend(extra_resolved)
            missing.extend(extra_missing)

        resolved = resolved[:target_count]
        if not resolved:
            raise tr.AppError("Spotify could not resolve any tracks from the regenerated playlist.")

        description = str(generated.get("description") or row["description"] or tr.spotify.DEFAULT_DESCRIPTION).strip()
        playlist = tr.spotify.create_playlist(
            token,
            name=str(generated.get("name") or row["name"] or "New Playlist").strip(),
            description=description,
            public=False,
        )
        tr.spotify.add_items(token, playlist["id"], [track["uri"] for track in resolved])
        tracks = [
            {
                "artist": ", ".join(artist["name"] for artist in track.get("artists", [])),
                "title": track["name"],
                "url": track.get("external_urls", {}).get("spotify"),
            }
            for track in resolved
        ]
        source_tracks = [
            {
                "artist": ", ".join(artist["name"] for artist in track.get("artists", [])),
                "title": track["name"],
                "source": "spotify-resolved-regeneration",
            }
            for track in resolved
        ]
        result = {
            "prompt": row["prompt"],
            "name": playlist.get("name", generated.get("name", row["name"])),
            "description": description,
            "tracks": tracks,
            "spotify_url": playlist.get("external_urls", {}).get("spotify"),
            "missing": missing,
            "source": "hybrid",
            "source_tracks": source_tracks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if len(tracks) < target_count:
            result["notice"] = f"Regeneration targeted {target_count} tracks but only {len(tracks)} resolved cleanly."

        with tr.database() as connection:
            cursor = connection.execute(
                "INSERT INTO generated_playlists (prompt, name, description, tracks, spotify_url, created_at, source, source_tracks) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result["prompt"], result["name"], result["description"], json.dumps(tracks),
                    result["spotify_url"], result["created_at"], result["source"], json.dumps(source_tracks),
                ),
            )
            result["id"] = cursor.lastrowid

        record(
            tr.database,
            "regenerate",
            playlist_id=result["id"],
            parent_playlist_id=playlist_id,
            prompt=str(row["prompt"] or ""),
            payload={
                "previous_tracks": previous_resolved,
                "new_tracks": tracks,
                "excluded_exact_tracks": excluded,
                "interpretation": "fresh_retry_not_negative_feedback",
            },
        )
        print(f"[Tune Raider] regenerate fresh retry: target {target_count}, resolved {len(tracks)}", flush=True)
        return jsonify(result)
    except (tr.AppError, tr.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


tr.app.view_functions["regenerate"] = regenerate_contextual
