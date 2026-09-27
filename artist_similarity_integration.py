"""Keep explicitly named artist-similarity prompts close to their anchor.

The core hybrid pool can drift when broad local genre matches arrive before direct
Last.fm neighbors. This hook reserves part of the external pool for artists Last.fm
says are directly similar to the artist named in prompts such as "songs like X".
"""
from __future__ import annotations

from contextvars import ContextVar

import requests

import app as tone_raider
import lastfm_client as lastfm
from anchor_policy import _prompt_artist_name

_original_external_candidates = tone_raider.lastfm_external_candidates
_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist
_prompt_anchor_artist: ContextVar[str] = ContextVar("prompt_anchor_artist", default="")


def _normalize(value: str) -> str:
    return tone_raider.spotify.normalize(str(value or ""))


def _direct_similarity_candidates(anchor: str, excluded_tracks=None, *, limit: int = 12) -> list[dict]:
    if not anchor or not lastfm.API_KEY or limit <= 0:
        return []

    excluded = tone_raider.excluded_track_keys(excluded_tracks)
    seen = set(excluded)
    result: list[dict] = []

    def add(artist: str, title: str, relationship: str, match: float | None = None) -> None:
        artist = str(artist or "").strip()
        title = str(title or "").strip()
        key = (_normalize(artist), _normalize(title))
        if not key[0] or not key[1] or key in seen or len(result) >= limit:
            return
        seen.add(key)
        row = {
            "artist": artist,
            "title": title,
            "source": "lastfm",
            "relationship": relationship,
            "anchor_artist": anchor,
        }
        if match is not None:
            row["match"] = round(float(match), 4)
        result.append(row)

    try:
        # Put a couple of anchor tracks into the model-visible pool as context even
        # though the post-curation safeguard will independently guarantee one survives.
        for title in lastfm.top_tracks(anchor, limit=2):
            add(anchor, title, f"track by prompt anchor {anchor}")

        for neighbor in lastfm.similar_artists(anchor, limit=10):
            match = float(neighbor.get("match") or 0)
            if match < 0.10:
                continue
            name = str(neighbor.get("name") or "").strip()
            if not name:
                continue
            for title in lastfm.top_tracks(name, limit=2):
                add(name, title, f"directly similar to prompt anchor {anchor}", match)
                if len(result) >= limit:
                    break
            if len(result) >= limit:
                break
    except (requests.RequestException, RuntimeError, ValueError):
        return result

    return result


def external_candidates_with_prompt_anchor(plan: dict, local_candidates: list[dict], excluded_tracks=None) -> list[dict]:
    existing = list(_original_external_candidates(plan, local_candidates, excluded_tracks) or [])
    anchor = _prompt_anchor_artist.get().strip()
    budget = max(0, tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT)
    if not anchor or budget == 0:
        return existing

    # Reserve about 60% of the external pool for direct anchor evidence. The rest
    # remains available to MusicBrainz/general Last.fm candidates so modifiers such
    # as "party", "slower", or "heavier" still have room to influence the result.
    direct_budget = min(12, max(6, int(round(budget * 0.6))))
    direct = _direct_similarity_candidates(anchor, excluded_tracks, limit=direct_budget)
    if not direct:
        return existing

    seen = {(_normalize(row.get("artist")), _normalize(row.get("title"))) for row in direct}
    merged = list(direct)
    for row in existing:
        if len(merged) >= budget:
            break
        key = (_normalize(row.get("artist")), _normalize(row.get("title")))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(row)

    print(
        f"[Tune Raider] prompt anchor {anchor!r}: reserved {len(direct)} direct Last.fm similarity candidates",
        flush=True,
    )
    return merged


def ask_for_hybrid_playlist_with_prompt_anchor(prompt: str, excluded_tracks=None) -> dict:
    anchor = _prompt_artist_name(prompt) or ""
    token = _prompt_anchor_artist.set(anchor)
    try:
        return _original_ask_for_hybrid_playlist(prompt, excluded_tracks)
    finally:
        _prompt_anchor_artist.reset(token)


tone_raider.lastfm_external_candidates = external_candidates_with_prompt_anchor
tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_prompt_anchor
