"""Keep playlist refinements tied to the musical identity of their parent playlist."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests
from flask import jsonify, request

import run_app

tr = run_app.tone_raider


def _root_prompt(row) -> str:
    """Preserve the best available original intent across refinement generations."""
    prompt = str(row["prompt"] or "").strip()
    if prompt.startswith("Original intent: "):
        root, _, _rest = prompt[len("Original intent: "):].partition(" || Refine ")
        return root.strip()
    if prompt.startswith("Refine "):
        # Older refinements did not persist lineage. The playlist description and
        # surviving tracks still provide useful musical context, but do not invent
        # an original prompt we no longer have.
        return ""
    return prompt


def _contextual_discovery_prompt(row, instruction: str, addition_prompt: str, remaining: list[dict]) -> str:
    root = _root_prompt(row)
    surviving = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in remaining[:12]
        if track.get("artist") and track.get("title")
    ]
    parts = [
        "Refine an existing playlist without changing its core musical identity.",
    ]
    if root:
        parts.append(f"Original discovery request: {root}")
    parts.append(f"Parent playlist: {row['name']}")
    if row["description"]:
        parts.append(f"Parent description: {row['description']}")
    if surviving:
        parts.append("Surviving musical reference tracks: " + "; ".join(surviving))
    parts.extend([
        f"Refinement request: {instruction}",
        f"Replacement goal: {addition_prompt or instruction}",
        "Discover replacements that fit the SAME genre, instrumentation, rhythmic character, production language, and energy envelope as the parent playlist. "
        "The surviving tracks are specimens, not permission to jump into their broader scenes. Do not fill space with merely adjacent punk, indie, folk, rock, or country if it breaks the parent's specific sound. "
        "Honor explicit exclusions permanently for this refinement. Prefer fewer correct replacements over unrelated filler.",
    ])
    return "\n".join(parts)


def _save_refined_playlist(source_row, instruction: str, requested_tracks: list[dict], name: str, description: str, target_count: int) -> dict:
    token = tr.spotify.get_access_token()
    resolved = []
    missing = []
    seen_uris = set()
    for requested_track in requested_tracks:
        req = tr.spotify.TrackRequest(
            str(requested_track.get("artist") or ""),
            str(requested_track.get("title") or ""),
        )
        track = tr.spotify.search_track(token, req)
        if track and track.get("uri") not in seen_uris:
            resolved.append(track)
            seen_uris.add(track["uri"])
        elif not track:
            missing.append(f"{req.artist} - {req.title}")

    if not resolved:
        raise tr.AppError("Spotify could not resolve any tracks for the refined playlist.")

    playlist = tr.spotify.create_playlist(token, name=name, description=description, public=False)
    tr.spotify.add_items(token, playlist["id"], [track["uri"] for track in resolved])
    tracks = [
        {
            "artist": ", ".join(artist["name"] for artist in track.get("artists", [])),
            "title": track["name"],
            "url": track.get("external_urls", {}).get("spotify"),
        }
        for track in resolved
    ]

    root = _root_prompt(source_row)
    prompt = (
        f"Original intent: {root} || Refine {source_row['name']}: {instruction}"
        if root else
        f"Refine {source_row['name']}: {instruction}"
    )
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
            "The revised playlist was still created with the usable matches rather than unrelated filler."
        )

    with tr.database() as connection:
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
        raise tr.AppError("That history item has no tracks to refine.")

    numbered = [
        {"index": index, "artist": track.get("artist", ""), "title": track.get("title", "")}
        for index, track in enumerate(current, 1)
    ]
    root = _root_prompt(row)
    plan = tr.model_json(
        "Revise an existing playlist according to the user's edit request. "
        "Return remove_indexes only for tracks the request clearly asks to remove or replace. "
        "Use addition_prompt to describe replacements, but preserve the parent playlist's musical identity unless the user explicitly asks for a stylistic change. "
        "Do not reinterpret a simple exclusion as permission to broaden genre. target_count should preserve the current count unless the user explicitly changes size. "
        "Preserve unaffected tracks and their order. Create a concise revised playlist name and one-sentence description. "
        "Existing playlist: " + json.dumps({
            "name": row["name"],
            "description": row["description"],
            "original_prompt": root or row["prompt"],
            "tracks": numbered,
        }),
        instruction,
        run_app.REFINEMENT_PLAN_SCHEMA,
        stage="playlist refinement",
    )

    remove_indexes = {
        int(value) for value in plan.get("remove_indexes", [])
        if isinstance(value, int) and 1 <= value <= len(current)
    }
    remaining = [track for index, track in enumerate(current, 1) if index not in remove_indexes]
    target_count = max(1, min(int(plan.get("target_count") or len(remaining) or 1), run_app.MAX_REFINEMENT_TRACKS))
    addition_prompt = str(plan.get("addition_prompt") or "").strip()

    additions = []
    if addition_prompt or target_count > len(remaining):
        discovery_prompt = _contextual_discovery_prompt(row, instruction, addition_prompt, remaining)
        excluded = [f"{track.get('artist', '')} - {track.get('title', '')}" for track in current]
        generated = tr.ask_for_hybrid_playlist(discovery_prompt, excluded)
        additions = list(generated.get("tracks") or [])

    final_tracks = run_app._merge_tracks(remaining, additions, target_count)

    # One second pass is allowed only inside the exact same parent context. Do not
    # call the old unconstrained broadener, which was the source of genre drift.
    if len(final_tracks) < target_count and additions:
        excluded = [f"{track.get('artist', '')} - {track.get('title', '')}" for track in final_tracks]
        strict_prompt = _contextual_discovery_prompt(row, instruction, addition_prompt, final_tracks)
        strict_prompt += "\nFind additional replacements only if they remain tightly inside this same sound. Do not broaden genre to hit the target count."
        second = tr.ask_for_hybrid_playlist(strict_prompt, excluded)
        final_tracks = run_app._merge_tracks(final_tracks, list(second.get("tracks") or []), target_count)

    name = str(plan.get("name") or f"{row['name']} · Refined").strip()
    description = str(plan.get("description") or row["description"] or tr.spotify.DEFAULT_DESCRIPTION).strip()
    return _save_refined_playlist(row, instruction, final_tracks, name, description, target_count)


def refine_history_item_contextual(playlist_id: int):
    body = request.get_json(silent=True) or {}
    instruction = str(body.get("instruction") or "").strip()
    if not instruction:
        return jsonify({"error": "Describe what you want to change about the playlist."}), 400

    with tr.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404

    try:
        return jsonify(_refine_playlist(row, instruction))
    except (tr.AppError, tr.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


# Replace the route function after run_app registers it.
tr.app.view_functions["refine_history_item"] = refine_history_item_contextual
