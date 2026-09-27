"""Local structured feedback/event storage for Tune Raider."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def record(database, event_type: str, *, playlist_id=None, parent_playlist_id=None, prompt="", instruction="", payload=None) -> None:
    """Persist an observed user action without over-interpreting it as preference.

    Regenerate is recorded as a request for another draw, not a dislike. Refinement
    events may include removed/surviving tracks and the user's literal instruction,
    which are stronger future learning signals.
    """
    with database() as connection:
        connection.execute(
            "INSERT INTO learning_events (event_type, playlist_id, parent_playlist_id, prompt, instruction, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(event_type), playlist_id, parent_playlist_id, str(prompt or ""), str(instruction or ""),
                json.dumps(payload or {}, separators=(",", ":")), datetime.now(timezone.utc).isoformat(),
            ),
        )
