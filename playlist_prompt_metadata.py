"""Embed recoverable generation prompts in Spotify playlist descriptions.

Spotify descriptions are user-visible, so retain editorial text and keep the
entire result within a conservative 300-character budget.
"""
from __future__ import annotations

MAX_DESCRIPTION = 300
MARKER = "Tune Raider prompt: "


def spotify_description(description: str, prompt: str, max_length: int = MAX_DESCRIPTION) -> str:
    description = " ".join(str(description or "").split())
    prompt = " ".join(str(prompt or "").split())
    if not prompt:
        return description[:max_length]
    # Prioritize the prompt because it cannot be recovered from the playlist
    # name, while the editorial text is optional. Truncation is explicit.
    available = max_length - len(MARKER)
    if available <= 0:
        return description[:max_length]
    if len(prompt) > available:
        prompt = prompt[:max(0, available - 1)].rstrip() + "…"
    prompt_field = MARKER + prompt
    room = max_length - len(prompt_field) - 3
    if room <= 0 or not description:
        return prompt_field
    if len(description) > room:
        description = description[:max(0, room - 1)].rstrip() + "…"
    return description + " | " + prompt_field


def extract_prompt(description: str) -> str | None:
    description = str(description or "")
    if MARKER not in description:
        return None
    prompt = description.rsplit(MARKER, 1)[1].strip()
    return prompt or None
