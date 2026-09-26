"""Small in-memory activity feed for the browser terminal.

Only Tune Raider/Ollama diagnostic lines are mirrored. Flask/Werkzeug request
logs are intentionally left out.
"""
from __future__ import annotations

import builtins
import threading
from collections import deque
from datetime import datetime, timezone

_PREFIXES = ("[Ollama]", "[Tune Raider]")
_MAX_LINES = 250
_lock = threading.Lock()
_entries = deque(maxlen=_MAX_LINES)
_sequence = 0
_installed = False
_original_print = builtins.print


def _record(message: str) -> None:
    global _sequence
    text = str(message or "").strip()
    if not text.startswith(_PREFIXES):
        return
    with _lock:
        _sequence += 1
        _entries.append({
            "id": _sequence,
            "message": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def _capturing_print(*args, **kwargs):
    sep = kwargs.get("sep", " ")
    try:
        text = sep.join(str(value) for value in args)
        for line in text.splitlines():
            _record(line)
    except Exception:
        pass
    return _original_print(*args, **kwargs)


def install_activity_capture() -> None:
    global _installed
    if _installed:
        return
    builtins.print = _capturing_print
    _installed = True


def activity_since(since: int = 0) -> dict:
    try:
        cursor = max(0, int(since))
    except (TypeError, ValueError):
        cursor = 0
    with _lock:
        latest = _sequence
        lines = [dict(entry) for entry in _entries if entry["id"] > cursor]
    return {"cursor": latest, "lines": lines}
