"""Retrieval helpers installed into app.py."""
from __future__ import annotations
import requests


def install(ns: dict) -> None:
    lastfm = ns["lastfm"]

    def compact_catalog_summary(library) -> dict:
        summary = library.summary()
        genres = [str(v).strip() for v in summary.get("genres", []) if str(v).strip()]
        return {"tracks": summary.get("tracks"), "genres": genres[:160], "axes": summary.get("axes", [])}

    def compact_local_candidate(row: dict, candidate_id: str, sound_axes: set[str]) -> dict:
        result = {"candidate_id": candidate_id, "source": "local", "artist": row.get("artist"), "title": row.get("title")}
        for key in ("album", "genre", "date"):
            value = row.get(key)
            if value not in (None, ""):
                result[key] = value
        sound = row.get("sound_percentiles")
        if isinstance(sound, dict) and sound_axes:
            filtered = {key: sound[key] for key in sound_axes if key in sound}
            if filtered:
                result["sound"] = filtered
        return result

    def enrich_library_plan(plan: dict, library) -> dict:
        enriched = {
            "artists": [str(v).strip() for v in plan.get("artists", []) if str(v).strip()],
            "terms": [str(v).strip() for v in plan.get("terms", []) if str(v).strip()],
            "sound": plan.get("sound", {}) if isinstance(plan.get("sound"), dict) else {},
        }
        if not lastfm.API_KEY:
            return enriched
        local = {str(r.get("artist") or "").casefold(): str(r.get("artist") or "") for r in library.rows}
        seen_artists = {v.casefold() for v in enriched["artists"]}
        seen_terms = {v.casefold() for v in enriched["terms"]}
        for seed in enriched["artists"][:4]:
            try:
                for tag in lastfm.filtered_top_tags(seed, min_weight=8, limit=5):
                    name = tag["name"]
                    if name.casefold() not in seen_terms:
                        enriched["terms"].append(name); seen_terms.add(name.casefold())
                for candidate in lastfm.similar_artists(seed, limit=10):
                    if candidate.get("match", 0) < 0.15:
                        continue
                    name = local.get(candidate["name"].casefold())
                    if name and name.casefold() not in seen_artists:
                        enriched["artists"].append(name); seen_artists.add(name.casefold())
            except (requests.RequestException, RuntimeError, ValueError):
                continue
        enriched["artists"] = enriched["artists"][:24]
        enriched["terms"] = enriched["terms"][:24]
        return enriched

    def excluded_track_keys(excluded_tracks) -> set[tuple[str, str]]:
        keys = set()
        for value in excluded_tracks or []:
            artist, sep, title = str(value).partition(" - ")
            if sep and artist.strip() and title.strip():
                keys.add((artist.strip().casefold(), title.strip().casefold()))
        return keys

    def lastfm_external_candidates(plan: dict, local_candidates: list[dict], excluded_tracks=None) -> list[dict]:
        if not lastfm.API_KEY:
            return []
        seen = set(excluded_track_keys(excluded_tracks)); result = []
        def add(artist, title, relationship, match=None):
            artist = str(artist or "").strip(); title = str(title or "").strip()
            key = (artist.casefold(), title.casefold())
            if not artist or not title or key in seen:
                return
            seen.add(key)
            row = {"artist": artist, "title": title, "source": "lastfm", "relationship": relationship}
            if match is not None: row["match"] = round(float(match), 4)
            result.append(row)
        seeds = []
        for value in list(plan.get("artists", [])) + [r.get("artist") for r in local_candidates]:
            name = str(value or "").strip()
            if name and name.casefold() not in {s.casefold() for s in seeds}: seeds.append(name)
            if len(seeds) >= 4: break
        for row in local_candidates[:4]:
            artist = str(row.get("artist") or "").strip(); title = str(row.get("title") or "").strip()
            if not artist or not title: continue
            try:
                for candidate in lastfm.similar_tracks(artist, title, limit=8):
                    if candidate.get("match", 0) >= 0.12:
                        add(candidate["artist"], candidate["title"], f"similar to {artist} - {title}", candidate.get("match"))
            except (requests.RequestException, RuntimeError, ValueError): pass
        for seed in seeds[:3]:
            try:
                for candidate in lastfm.similar_artists(seed, limit=5):
                    if candidate.get("match", 0) < 0.15: continue
                    for title in lastfm.top_tracks(candidate["name"], limit=3):
                        add(candidate["name"], title, f"artist similar to {seed}", candidate.get("match"))
            except (requests.RequestException, RuntimeError, ValueError): pass
        return result[:50]

    ns.update({"compact_catalog_summary": compact_catalog_summary, "compact_local_candidate": compact_local_candidate,
               "enrich_library_plan": enrich_library_plan, "excluded_track_keys": excluded_track_keys,
               "lastfm_external_candidates": lastfm_external_candidates})
