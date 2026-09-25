#!/usr/bin/env python3
"""Tune Raider application entrypoint with post-curation safeguards."""
from __future__ import annotations

import os

import app as tone_raider
from anchor_policy import ensure_prompt_anchor


_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist


def ask_for_hybrid_playlist_with_anchor(prompt: str, excluded_tracks=None) -> dict:
    generated = _original_ask_for_hybrid_playlist(prompt, excluded_tracks)
    return ensure_prompt_anchor(
        prompt,
        generated,
        tone_raider.AUDIO_DATABASE,
        excluded_tracks=excluded_tracks,
        track_limit=tone_raider.PLAYLIST_TRACK_LIMIT,
        artist_limit=tone_raider.PLAYLIST_ARTIST_LIMIT,
    )


tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_anchor


if __name__ == "__main__":
    tone_raider.app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
