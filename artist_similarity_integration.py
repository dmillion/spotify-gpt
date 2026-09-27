"""Keep explicitly named artist-similarity prompts close to their anchor.

For "songs like X" requests, Tune Raider treats X's actual style profile as the
primary constraint. Collaborative similarity alone can connect artists that share
listeners but not much sound, so direct neighbors are filtered/ranked by overlap
with the anchor's Last.fm/MusicBrainz tags before they enter the curator pool.
"""
from __future__ import annotations

from contextvars import ContextVar

import requests

import app as tone_raider
import lastfm_client as lastfm
import musicbrainz_client as musicbrainz
from anchor_policy import _prompt_artist_name

_original_enrich_library_plan = tone_raider.enrich_library_plan
_original_external_candidates = tone_raider.lastfm_external_candidates
_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist
_prompt_anchor_artist: ContextVar[str] = ContextVar("prompt_anchor_artist", default="")

# Tags this broad are weak evidence by themselves. They can still contribute to a
# match, but a single overlap such as "folk" or "rock" should not pull a playlist
# into an unrelated scene.
_GENERIC_STYLE_TAGS = {
    "rock", "indie", "indie rock", "alternative", "alternative rock", "folk",
    "country", "pop", "jazz", "blues", "singer-songwriter", "americana",
}


def _normalize(value: str) -> str:
    return tone_raider.spotify.normalize(str(value or ""))


def _style_key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _anchor_style_profile(anchor: str) -> list[str]:
    """Collect the strongest available genre/style vocabulary for the anchor."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = _style_key(value)
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)

    if lastfm.API_KEY:
        try:
            for tag in lastfm.filtered_top_tags(anchor, min_weight=3, limit=10):
                add(tag.get("name", ""))
        except (requests.RequestException, RuntimeError, ValueError):
            pass

    if musicbrainz.ENABLED:
        try:
            for tag in musicbrainz.artist_tags(anchor, limit=8):
                add(tag.get("name", ""))
        except (requests.RequestException, RuntimeError, ValueError):
            pass

    return ordered[:12]


def _neighbor_style_score(anchor_styles: list[str], neighbor: str) -> tuple[float, list[str]]:
    """Return style-overlap score and matching tags for a candidate neighbor."""
    if not anchor_styles or not lastfm.API_KEY:
        return 0.0, []
    try:
        neighbor_tags = lastfm.filtered_top_tags(neighbor, min_weight=3, limit=10)
    except (requests.RequestException, RuntimeError, ValueError):
        return 0.0, []

    anchor_set = {_style_key(tag) for tag in anchor_styles}
    candidate_set = {_style_key(tag.get("name", "")) for tag in neighbor_tags}
    overlap = [tag for tag in anchor_styles if _style_key(tag) in candidate_set]
    if not overlap:
        return 0.0, []

    specific = [tag for tag in overlap if _style_key(tag) not in _GENERIC_STYLE_TAGS]
    # Specific overlap is much stronger than broad umbrella tags. Multiple broad
    # overlaps can still establish a reasonable connection.
    score = len(specific) * 2.5 + (len(overlap) - len(specific)) * 0.75
    score /= max(3.0, min(8.0, float(len(anchor_set))))
    return score, overlap


def enrich_library_plan_with_anchor_styles(plan: dict, library) -> dict:
    """Make local retrieval honor the named artist's actual genre/style first."""
    enriched = _original_enrich_library_plan(plan, library)
    anchor = _prompt_anchor_artist.get().strip()
    if not anchor:
        return enriched

    styles = _anchor_style_profile(anchor)
    if not styles:
        return enriched

    terms = [str(value).strip() for value in enriched.get("terms", []) if str(value).strip()]
    seen = {_style_key(value) for value in terms}
    # Put anchor-derived terms first so they survive the existing 24-term cap.
    anchor_terms = [style for style in styles if _style_key(style) not in seen]
    enriched["terms"] = (anchor_terms + terms)[:24]
    print(
        f"[Tune Raider] prompt anchor {anchor!r}: style profile -> {', '.join(styles[:8])}",
        flush=True,
    )
    return enriched


def _direct_similarity_candidates(anchor: str, excluded_tracks=None, *, limit: int = 12) -> list[dict]:
    if not anchor or not lastfm.API_KEY or limit <= 0:
        return []

    excluded = tone_raider.excluded_track_keys(excluded_tracks)
    seen = set(excluded)
    result: list[dict] = []
    anchor_styles = _anchor_style_profile(anchor)

    def add(artist: str, title: str, relationship: str, match: float | None = None, style_overlap=None) -> None:
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
        if anchor_styles:
            row["anchor_styles"] = anchor_styles[:8]
        if style_overlap:
            row["style_overlap"] = list(style_overlap)[:6]
        if match is not None:
            row["match"] = round(float(match), 4)
        result.append(row)

    try:
        # Anchor tracks give the curator a concrete center of gravity.
        for title in lastfm.top_tracks(anchor, limit=2):
            add(anchor, title, f"track by prompt anchor {anchor}", style_overlap=anchor_styles[:6])

        ranked_neighbors = []
        for neighbor in lastfm.similar_artists(anchor, limit=18):
            match = float(neighbor.get("match") or 0)
            if match < 0.10:
                continue
            name = str(neighbor.get("name") or "").strip()
            if not name:
                continue
            style_score, overlap = _neighbor_style_score(anchor_styles, name)
            specific_overlap = [tag for tag in overlap if _style_key(tag) not in _GENERIC_STYLE_TAGS]

            # When we know the anchor's style, listener-similarity alone is not enough.
            # Require either a specific shared style, multiple broad style matches, or
            # an exceptionally strong Last.fm relationship.
            if anchor_styles and not (
                specific_overlap
                or len(overlap) >= 2
                or match >= 0.55
            ):
                continue
            combined = match + style_score
            ranked_neighbors.append((combined, match, name, overlap))

        ranked_neighbors.sort(key=lambda row: row[0], reverse=True)
        for _combined, match, name, overlap in ranked_neighbors:
            relationship = f"style-matched neighbor of {anchor}"
            if overlap:
                relationship += f"; shared styles: {', '.join(overlap[:4])}"
            for title in lastfm.top_tracks(name, limit=2):
                add(name, title, relationship, match, overlap)
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

    # For explicit "like artist" prompts, stylistic fidelity should dominate. Keep
    # roughly 70% of the external pool tied directly to the anchor profile and leave
    # the remainder for modifiers such as party, slower, heavier, or more melodic.
    direct_budget = min(14, max(8, int(round(budget * 0.7))))
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
        f"[Tune Raider] prompt anchor {anchor!r}: reserved {len(direct)} genre-matched similarity candidates",
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


tone_raider.enrich_library_plan = enrich_library_plan_with_anchor_styles
tone_raider.lastfm_external_candidates = external_candidates_with_prompt_anchor
tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_prompt_anchor
