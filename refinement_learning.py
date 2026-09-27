"""Persist refinement actions as structured local learning signals."""
from __future__ import annotations

import json

import refinement_context
from learning_store import record

tr = refinement_context.tr
_original_refine = refinement_context._refine_playlist


def _refine_with_learning(row, instruction: str) -> dict:
    before = json.loads(row["source_tracks"]) or json.loads(row["tracks"]) or []
    result = _original_refine(row, instruction)
    after = list(result.get("source_tracks") or result.get("tracks") or [])

    before_keys = {
        (str(track.get("artist") or "").casefold(), str(track.get("title") or "").casefold())
        for track in before
    }
    after_keys = {
        (str(track.get("artist") or "").casefold(), str(track.get("title") or "").casefold())
        for track in after
    }
    removed = [
        track for track in before
        if (str(track.get("artist") or "").casefold(), str(track.get("title") or "").casefold()) not in after_keys
    ]
    surviving = [
        track for track in before
        if (str(track.get("artist") or "").casefold(), str(track.get("title") or "").casefold()) in after_keys
    ]
    added = [
        track for track in after
        if (str(track.get("artist") or "").casefold(), str(track.get("title") or "").casefold()) not in before_keys
    ]

    record(
        tr.database,
        "refine",
        playlist_id=result.get("id"),
        parent_playlist_id=row["id"],
        prompt=str(row["prompt"] or ""),
        instruction=instruction,
        payload={
            "removed_tracks": removed,
            "surviving_tracks": surviving,
            "added_tracks": added,
            "interpretation": "explicit_iteration_signal",
        },
    )
    return result


refinement_context._refine_playlist = _refine_with_learning
