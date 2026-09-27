"""Make iterative actions honor the playlist's current Spotify state."""
from __future__ import annotations

import json

import requests
from flask import jsonify, request

import refinement_context
import run_app
from learning_store import record
from spotify_playlist_state import (
    as_exclusions,
    compare_stored_to_live,
    ensure_playlist_read_scope,
    fetch_playlist_tracks,
)

tr = run_app.tone_raider


def _discovery_prompt(row, instruction: str, addition_prompt: str, remaining: list[dict], manual_removed: list[dict]) -> str:
    root = refinement_context._root_prompt(row)
    specimens = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in remaining[:16]
        if track.get("artist") and track.get("title")
    ]
    removed = as_exclusions(manual_removed)
    parts = ["Refine the current Spotify playlist without losing its core musical identity."]
    if root:
        parts.append(f"Original discovery request: {root}")
    if row["description"]:
        parts.append(f"Playlist description: {row['description']}")
    if specimens:
        parts.append("Tracks currently still in the Spotify playlist, and therefore positive style specimens: " + "; ".join(specimens))
    if removed:
        parts.append("Tracks the user manually removed from Spotify. Do NOT recommend these again in this iteration: " + "; ".join(removed))
    parts.extend([
        f"Refinement request: {instruction}",
        f"Replacement/addition goal: {addition_prompt or instruction}",
        "Use the full discovery stack, but keep replacements inside the specific genre, instrumentation, rhythmic feel, production language, and energy implied by the original request and the surviving playlist. Manual removals are negative evidence for this iteration. Prefer fewer correct choices over unrelated filler.",
    ])
    return "\n".join(parts)


def _refine_live(row, instruction: str) -> dict:
    stored = json.loads(row["tracks"]) or json.loads(row["source_tracks"]) or []
    ensure_playlist_read_scope(tr.spotify)
    token = tr.spotify.get_access_token()
    _playlist_id, live = fetch_playlist_tracks(tr.spotify, token, row["spotify_url"])
    manual_removed, manual_added = compare_stored_to_live(tr.spotify, stored, live)

    if manual_removed or manual_added:
        record(
            tr.database,
            "spotify_manual_edit_observed",
            parent_playlist_id=row["id"],
            prompt=str(row["prompt"] or ""),
            payload={"removed_tracks": manual_removed, "added_tracks": manual_added},
        )
        print(
            f"[Tune Raider] Spotify sync before refine: {len(live)} live, {len(manual_removed)} manually removed, {len(manual_added)} manually added",
            flush=True,
        )

    numbered = [
        {"index": index, "artist": track.get("artist", ""), "title": track.get("title", "")}
        for index, track in enumerate(live, 1)
    ]
    root = refinement_context._root_prompt(row)
    plan = tr.model_json(
        "Revise an existing playlist according to the user's edit request. The listed tracks are the CURRENT Spotify playlist, not a stale local snapshot. "
        "Return remove_indexes only for current tracks the request clearly asks to remove or replace. Use addition_prompt for new discovery. "
        "Preserve unaffected tracks and their order. target_count should preserve the current live count unless the user asks to add or remove a quantity. "
        "Create a concise revised name and one-sentence description. Existing playlist: " + json.dumps({
            "name": row["name"], "description": row["description"], "original_prompt": root or row["prompt"], "tracks": numbered,
        }),
        instruction,
        run_app.REFINEMENT_PLAN_SCHEMA,
        stage="playlist refinement",
    )

    remove_indexes = {
        int(value) for value in plan.get("remove_indexes", [])
        if isinstance(value, int) and 1 <= value <= len(live)
    }
    remaining = [track for index, track in enumerate(live, 1) if index not in remove_indexes]
    target_count = max(1, min(int(plan.get("target_count") or len(live) or 1), run_app.MAX_REFINEMENT_TRACKS))
    addition_prompt = str(plan.get("addition_prompt") or "").strip()

    additions: list[dict] = []
    if addition_prompt or target_count > len(remaining):
        prompt = _discovery_prompt(row, instruction, addition_prompt, remaining, manual_removed)
        excluded = as_exclusions(live + manual_removed)
        generated = tr.ask_for_hybrid_playlist(prompt, excluded)
        additions = list(generated.get("tracks") or [])

    final_tracks = run_app._merge_tracks(remaining, additions, target_count)
    if len(final_tracks) < target_count and additions:
        prompt = _discovery_prompt(row, instruction, addition_prompt, final_tracks, manual_removed)
        prompt += "\nFind more only if they remain tightly inside this same sound."
        excluded = as_exclusions(final_tracks + manual_removed)
        second = tr.ask_for_hybrid_playlist(prompt, excluded)
        final_tracks = run_app._merge_tracks(final_tracks, list(second.get("tracks") or []), target_count)

    name = str(plan.get("name") or f"{row['name']} · Refined").strip()
    description = str(plan.get("description") or row["description"] or tr.spotify.DEFAULT_DESCRIPTION).strip()
    result = refinement_context._save_refined_playlist(row, instruction, final_tracks, name, description, target_count)

    before_keys = {(tr.spotify.normalize(t.get("artist", "")), tr.spotify.normalize(t.get("title", ""))) for t in live}
    after = list(result.get("source_tracks") or result.get("tracks") or [])
    after_keys = {(tr.spotify.normalize(t.get("artist", "")), tr.spotify.normalize(t.get("title", ""))) for t in after}
    record(
        tr.database,
        "refine_live",
        playlist_id=result.get("id"),
        parent_playlist_id=row["id"],
        prompt=str(root or row["prompt"] or ""),
        instruction=instruction,
        payload={
            "manual_removed_tracks": manual_removed,
            "manual_added_tracks": manual_added,
            "removed_by_refinement": [t for t in live if (tr.spotify.normalize(t.get("artist", "")), tr.spotify.normalize(t.get("title", ""))) not in after_keys],
            "surviving_tracks": [t for t in live if (tr.spotify.normalize(t.get("artist", "")), tr.spotify.normalize(t.get("title", ""))) in after_keys],
            "added_tracks": [t for t in after if (tr.spotify.normalize(t.get("artist", "")), tr.spotify.normalize(t.get("title", ""))) not in before_keys],
        },
    )
    return result


def refine_history_item_live(playlist_id: int):
    body = request.get_json(silent=True) or {}
    instruction = str(body.get("instruction") or "").strip()
    if not instruction:
        return jsonify({"error": "Describe what you want to change about the playlist."}), 400
    with tr.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404
    try:
        return jsonify(_refine_live(row, instruction))
    except (tr.AppError, tr.spotify.SpotifyError, requests.RequestException, ValueError) as exc:
        return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)


tr.app.view_functions["refine_history_item"] = refine_history_item_live
