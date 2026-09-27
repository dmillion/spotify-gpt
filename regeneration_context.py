"""Context-preserving regeneration with Spotify-resolution backfill."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests
from flask import jsonify

import run_app
from preference_policy import artist_blocked

tr = run_app.tone_raider


def _style_prompt(row, previous: list[dict], *, refill: bool = False) -> str:
    specimens = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in previous[:16]
        if track.get("artist") and track.get("title")
    ]
    parts = [
        str(row["prompt"] or "").strip(),
        "Generate an alternate version of this playlist, but stay tightly connected to the same source sound.",
        "The previous playlist tracks below are positive style specimens, not merely exclusions. Use them to understand what worked: genre, instrumentation, rhythmic feel, production language, energy, and proximity to the named inspiration.",
    ]
    if row["description"]:
        parts.append(f"Previous playlist description: {row['description']}")
    if specimens:
        parts.append("Previous successful style specimens: " + "; ".join(specimens))
    parts.append(
        "Do not repeat those exact tracks, but find different tracks that are at least as close to the original inspiration and requested mood. Do not broaden into merely adjacent scenes just to fill space. Prefer more correct tracks over fewer when enough strong candidates exist."
    )
    if refill:
        parts.append(
            "This is a refill pass because some otherwise-good candidates could not be resolved on Spotify. Find additional alternatives inside the SAME style envelope; do not loosen genre or source proximity."
        )
    return "\n".join(part for part in parts if part)


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
        prompt = _style_prompt(row, previous)
        generated = tr.ask_for_hybrid_playlist(prompt, excluded)
        requested = list(generated.get("tracks") or [])

        token = tr.spotify.get_access_token()
        seen_uris: set[str] = set()
        resolved, missing = _resolve(token, requested, seen_uris=seen_uris)

        # Resolution failures should not silently shrink a regeneration. Run one
        # tightly constrained refill pass and resolve only genuinely new tracks.
        if len(resolved) < target_count:
            refill_excluded = excluded + [
                f"{', '.join(a['name'] for a in track.get('artists', []))} - {track.get('name', '')}"
                for track in resolved
            ]
            refill_prompt = _style_prompt(row, previous, refill=True)
            refill = tr.ask_for_hybrid_playlist(refill_prompt, refill_excluded)
            extra_requested = list(refill.get("tracks") or [])
            extra_resolved, extra_missing = _resolve(token, extra_requested, seen_uris=seen_uris)
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
            result["notice"] = (
                f"Regeneration targeted {target_count} tracks but only {len(tracks)} could be resolved while staying inside the source sound."
            )

        with tr.database() as connection:
            cursor = connection.execute(
                "INSERT INTO generated_playlists (prompt, name, description, tracks, spotify_url, created_at, source, source_tracks) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result["prompt"], result["name"], result["description"], json.dumps(tracks),
                    result["spotify_url"], result["created_at"], result["source"], json.dumps(source_tracks),
                ),
            )
            result["id"] = cursor.lastrowid

        print(
            f"[Tune Raider] regenerate: target {target_count}, resolved {len(tracks)}, unresolved candidates {len(missing)}",
            flush=True,
        )
        return jsonify(result)
    except (tr.AppError, tr.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


# Replace the route registered by app.py after run_app has installed safeguards.
tr.app.view_functions["regenerate"] = regenerate_contextual
