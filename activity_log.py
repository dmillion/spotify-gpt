"""Mirror selected Tune Raider diagnostics into a browser-readable activity feed.

Only Tune Raider/Ollama diagnostic lines are mirrored. Flask/Werkzeug request
logs are intentionally left out.
"""
from __future__ import annotations

import builtins
import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

_PREFIXES = ("[Ollama]", "[Tune Raider]")
_MAX_LINES = 250
_feed_path = Path(__file__).parent / "static" / "activity.json"
_lock = threading.Lock()
_entries = deque(maxlen=_MAX_LINES)
_sequence = 0
_installed = False
_original_print = builtins.print


def _publish_locked() -> None:
    _feed_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _feed_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"cursor": _sequence, "lines": list(_entries)}, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(_feed_path)


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
        try:
            _publish_locked()
        except OSError:
            pass


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
    with _lock:
        try:
            _publish_locked()
        except OSError:
            pass
