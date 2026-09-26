"""Runtime MusicBrainz enrichment hooks for Tune Raider.

This module patches the existing app before run_app installs its own safeguards,
so MusicBrainz participates in retrieval without duplicating the core playlist
pipeline.
"""
from __future__ import annotations

from contextvars import ContextVar

import requests

import app as tone_raider
import musicbrainz_client as musicbrainz

_original_enrich_library_plan = tone_raider.enrich_library_plan
_original_external_candidates = tone_raider.lastfm_external_candidates
_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist
_musicbrainz_candidate_keys: ContextVar[set[tuple[str, str]]] = ContextVar(
    "musicbrainz_candidate_keys", default=set()
)


def _normalize(value: str) -> str:
    return tone_raider.spotify.normalize(str(value or ""))


def enrich_library_plan_with_musicbrainz(plan: dict, library) -> dict:
    enriched = _original_enrich_library_plan(plan, library)
    if not musicbrainz.ENABLED:
        return enriched

    local_artist_lookup = {
        _normalize(row.get("artist")): str(row.get("artist") or "")
        for row in library.rows
        if str(row.get("artist") or "").strip()
    }
    seen_artists = {_normalize(value) for value in enriched.get("artists", [])}
    seen_terms = {_normalize(value) for value in enriched.get("terms", [])}

    # Keep MusicBrainz bounded: each seed may cost a lookup plus one detail call,
    # and the public service asks clients to stay near one request per second.
    for seed in list(enriched.get("artists", []))[:3]:
        try:
            for tag in musicbrainz.artist_tags(seed, limit=5):
                name = str(tag.get("name") or "").strip()
                key = _normalize(name)
                if name and key not in seen_terms:
                    enriched.setdefault("terms", []).append(name)
                    seen_terms.add(key)

            for related in musicbrainz.related_artists(seed, limit=8):
                local_name = local_artist_lookup.get(_normalize(related))
                key = _normalize(local_name)
                if local_name and key not in seen_artists:
                    enriched.setdefault("artists", []).append(local_name)
                    seen_artists.add(key)
        except (requests.RequestException, RuntimeError, ValueError):
            continue

    enriched["artists"] = list(enriched.get("artists", []))[:24]
    enriched["terms"] = list(enriched.get("terms", []))[:24]
    return enriched


def external_candidates_with_musicbrainz(plan: dict, local_candidates: list[dict], excluded_tracks=None) -> list[dict]:
    existing = list(_original_external_candidates(plan, local_candidates, excluded_tracks) or [])
    if not musicbrainz.ENABLED or tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT <= len(existing):
        _musicbrainz_candidate_keys.set(set())
        return existing

    excluded = tone_raider.excluded_track_keys(excluded_tracks)
    seen = set(excluded)
    for row in existing:
        seen.add((_normalize(row.get("artist")), _normalize(row.get("title"))))

    seeds = []
    seed_seen = set()
    for value in list(plan.get("artists") or []) + [row.get("artist") for row in local_candidates[:12]]:
        name = str(value or "").strip()
        key = _normalize(name)
        if name and key and key not in seed_seen:
            seeds.append(name)
            seed_seen.add(key)
        if len(seeds) >= 4:
            break

    remaining = max(0, tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT - len(existing))
    added = []
    mb_keys = set()
    for seed in seeds:
        if len(added) >= remaining:
            break
        try:
            recordings = musicbrainz.recordings_by_artist(seed, limit=min(8, remaining - len(added)))
        except (requests.RequestException, RuntimeError, ValueError):
            continue
        for row in recordings:
            key = (_normalize(row.get("artist")), _normalize(row.get("title")))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            mb_keys.add(key)
            added.append({
                "artist": row["artist"],
                "title": row["title"],
                "source": "musicbrainz",
            })
            if len(added) >= remaining:
                break

    _musicbrainz_candidate_keys.set(mb_keys)
    if added:
        print(
            f"[Tune Raider] MusicBrainz supplemented external pool with {len(added)} recordings",
            flush=True,
        )
    return existing + added


def ask_for_hybrid_playlist_with_musicbrainz_labels(prompt: str, excluded_tracks=None) -> dict:
    generated = _original_ask_for_hybrid_playlist(prompt, excluded_tracks)
    mb_keys = _musicbrainz_candidate_keys.get()
    if not mb_keys:
        return generated
    for track in generated.get("tracks") or []:
        key = (_normalize(track.get("artist")), _normalize(track.get("title")))
        if key in mb_keys:
            track["source"] = "musicbrainz"
    return generated


tone_raider.enrich_library_plan = enrich_library_plan_with_musicbrainz
tone_raider.lastfm_external_candidates = external_candidates_with_musicbrainz
tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_musicbrainz_labels
