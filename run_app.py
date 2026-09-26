#!/usr/bin/env python3
"""Tune Raider application entrypoint with post-curation safeguards."""
from __future__ import annotations

import os

from flask import jsonify

import app as tone_raider
from anchor_policy import ensure_prompt_anchor
from intent_policy import apply_request_constraints, has_title_constraint


_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist


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
    # prompts. Skipping anchor inference here prevents a word such as "goat" from
    # accidentally being interpreted as an artist named Goat.
    if not has_title_constraint(prompt):
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
