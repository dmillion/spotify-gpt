"""Keep explicitly named artist-similarity prompts close to their anchor.

For "songs like X" requests, Tune Raider treats X's actual style profile as the
primary constraint. The local library is useful evidence about the user's taste,
but it is not the destination: discovery-first requests should mostly expand into
new external music rather than recycle whatever happens to be indexed locally.
"""
from __future__ import annotations

from contextvars import ContextVar
import random
import os
from collections import Counter

import discovery_novelty
import discovery_track_fit
from anchor_policy import _prompt_track_requests

import requests

import app as tone_raider
import lastfm_client as lastfm
import musicbrainz_client as musicbrainz
from anchor_policy import _prompt_artist_name

_original_enrich_library_plan = tone_raider.enrich_library_plan
_original_external_candidates = tone_raider.lastfm_external_candidates
_original_ask_for_hybrid_playlist = tone_raider.ask_for_hybrid_playlist
_prompt_anchor_artist: ContextVar[str] = ContextVar("prompt_anchor_artist", default="")
_active_discovery_prompt: ContextVar[str] = ContextVar("active_discovery_prompt", default="")

# Broad umbrella tags are weak evidence by themselves. A single overlap like
# "folk" or "rock" must not be enough to drag a playlist into an unrelated scene.
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
    score = len(specific) * 2.5 + (len(overlap) - len(specific)) * 0.75
    score /= max(3.0, min(8.0, float(len(anchor_set))))
    return score, overlap


def _style_match(anchor_styles: list[str], artist: str) -> tuple[bool, list[str]]:
    """Decide whether an artist is close enough to the anchor's actual style."""
    if not anchor_styles:
        return True, []
    _score, overlap = _neighbor_style_score(anchor_styles, artist)
    specific = [tag for tag in overlap if _style_key(tag) not in _GENERIC_STYLE_TAGS]
    return bool(specific or len(overlap) >= 2), overlap


def enrich_library_plan_with_anchor_styles(plan: dict, library) -> dict:
    """Use the library as a reference signal without making it the discovery goal."""
    enriched = _original_enrich_library_plan(plan, library)
    anchor = _prompt_anchor_artist.get().strip()
    if not anchor:
        return enriched

    styles = _anchor_style_profile(anchor)
    if not styles:
        return enriched

    terms = [str(value).strip() for value in enriched.get("terms", []) if str(value).strip()]
    seen = {_style_key(value) for value in terms}
    anchor_terms = [style for style in styles if _style_key(style) not in seen]
    enriched["terms"] = (anchor_terms + terms)[:24]
    print(
        f"[Tune Raider] prompt anchor {anchor!r}: style profile -> {', '.join(styles[:8])}",
        flush=True,
    )
    return enriched


def _debug():
    return os.environ.get("DISCOVERY_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}


def _history():
    """Historical selections inform novelty, without excluding viable recordings."""
    try:
        with tone_raider.database() as connection:
            return discovery_novelty.history_counts(connection)
    except Exception as exc:
        print(f"[Tune Raider] discovery history unavailable: {exc}", flush=True)
        return Counter(), Counter()


def _novelty_order(candidates, prompt, *, limit):
    """Rank before model curation; emphasize track freshness over artist familiarity.

    Novelty is a tie-breaker for strongly related songs, not a hard blacklist.
    Generic genre prompts receive the same history protection.
    """
    track_counts, artist_counts = _history()
    refs = {(discovery_novelty.artist_key(ref.artist), discovery_novelty.norm(ref.title))
            for ref in _prompt_track_requests(prompt)}
    seen = set()
    ranked = []
    rejected = Counter()
    # Broad genre prompts need stronger artist rotation; explicit song references
    # should prioritize sonic proximity without locking into the same recordings.
    broad = not refs
    artist_penalty = 4.5 if broad else 2.5
    track_penalty = 55 if broad else 45
    rng = random.SystemRandom()
    for index, row in enumerate(candidates):
        key = discovery_novelty.track_key(row)
        if not all(key):
            rejected["invalid"] += 1
            continue
        if key in seen:
            rejected["duplicate"] += 1
            continue
        seen.add(key)
        if key in refs:
            rejected["reference"] += 1
            continue  # Anchor policy adds mandatory references separately.
        match = max(0.0, min(1.0, float(row.get("match") or 0.0)))
        style = len(row.get("style_overlap") or [])
        # Exact recording repeats are penalized more than repeated artists.
        # A strong match can still win when fresh candidates are weak.
        # Artist-level similarity is only a discovery lead, not track-level fit.
        score = (match * 16 + min(style, 4) * 3
                 - track_counts[key] * track_penalty
                 - min(artist_counts[key[0]], 12) * artist_penalty
                 + rng.uniform(0, 1.5))
        # Explicit reference-track neighbors carry stronger song-level evidence.
        if str(row.get("relationship") or "").startswith("track neighbor of "):
            score += 13
        ranked.append((score, index, row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    # Request track tags only for the strongest leads, not every discovered song.
    # This limits added Last.fm requests and prevents an unbounded latency increase.
    if any(discovery_track_fit.sonic_ranking.intent(prompt).values()):
        reranked = []
        for position, (score, index, row) in enumerate(ranked):
            evidence = {}
            if position < 32:
                delta, evidence = discovery_track_fit.adjustment(
                    prompt, row.get("artist", ""), row.get("title", ""))
                score += delta
            if evidence:
                row = dict(row)
                row["track_fit_evidence"] = evidence
            reranked.append((score, index, row))
        ranked = sorted(reranked, key=lambda item: (-item[0], item[1]))
    output = []
    artist_usage = Counter()
    soft_limit = 2
    hard_limit = 5
    for _, _, row in ranked:
        artist = discovery_novelty.artist_key(row.get("artist"))
        if artist_usage[artist] >= hard_limit:
            rejected["artist_cap"] += 1
            continue
        if artist_usage[artist] >= soft_limit:
            rejected["soft_artist_penalty"] += 1
        artist_usage[artist] += 1
        output.append(row)
        if len(output) >= limit:
            break
    print(f"[Tune Raider] discovery novelty: {len(candidates)} candidates -> "
          f"{len(output)}; {sum(track_counts[discovery_novelty.track_key(t)] > 0 for t in output)} historical repeats",
          flush=True)
    if _debug():
        print(f"[Tune Raider] discovery funnel: scored={len(ranked)} selected={len(output)} "
              f"budget={limit} rejected={dict(rejected)}", flush=True)
        chosen = {discovery_novelty.track_key(row) for row in output}
        for score_value, _, row in ranked[:12]:
            key = discovery_novelty.track_key(row)
            print(f"[Tune Raider] discovery ranked: {row.get('artist')} / {row.get('title')} "
                  f"score={score_value:.1f} match={row.get('match', 0)} "
                  f"history={track_counts[key]} artist_history={artist_counts[key[0]]} "
                  f"selected={key in chosen}", flush=True)
        missed = [row for _, _, row in ranked if discovery_novelty.track_key(row) not in chosen]
        for row in missed[:12]:
            print(f"[Tune Raider] discovery missed: {row.get('artist')} / {row.get('title')} "
                  f"reason=artist_cap_or_budget", flush=True)
    return output


def _direct_similarity_candidates(anchor: str, excluded_tracks=None, *, limit: int = 12) -> list[dict]:
    """Blend reference-track neighbors with artist neighbors, ranked for novelty.

    The Last.fm request budget is bounded; no additional model calls are made.
    """
    if not anchor or not lastfm.API_KEY or limit <= 0:
        return []
    prompt = _active_discovery_prompt.get()
    excluded = tone_raider.excluded_track_keys(excluded_tracks)
    seen = set(excluded)
    pool = []
    anchor_styles = _anchor_style_profile(anchor)
    rng = random.SystemRandom()
    max_pool = min(100, max(limit * 3, 40))
    stats = Counter()

    def add(artist, title, relationship, match=0.0, overlap=None):
        artist = str(artist or "").strip()
        title = str(title or "").strip()
        key = (_normalize(artist), _normalize(title))
        if not all(key):
            stats["invalid"] += 1
            return
        if key in seen:
            stats["duplicate_or_excluded"] += 1
            return
        if len(pool) >= max_pool:
            stats["pool_full"] += 1
            return
        if _normalize(artist) == _normalize(anchor):
            stats["anchor_artist"] += 1
            return
        seen.add(key)
        stats["pooled"] += 1
        pool.append({
            "artist": artist, "title": title, "source": "lastfm",
            "relationship": relationship, "anchor_artist": anchor,
            "match": round(float(match or 0), 4),
            "style_overlap": list(overlap or [])[:6],
        })

    # Track-level neighbors expand beyond the same artist similarity cluster.
    for ref in _prompt_track_requests(prompt)[:3]:
        try:
            for item in lastfm.similar_tracks(ref.artist, ref.title, limit=50):
                artist = str(item.get("artist") or "")
                match = float(item.get("match") or 0)
                if match < 0.12:
                    stats["track_low_similarity"] += 1
                    continue
                style_score, overlap = _neighbor_style_score(anchor_styles, artist)
                if anchor_styles and not (style_score > 0 or match >= 0.65):
                    stats["track_style_rejected"] += 1
                    continue
                add(artist, item.get("title"), f"track neighbor of {ref.title}",
                    match, overlap)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"[Tune Raider] reference-track discovery unavailable: {exc}", flush=True)

    try:
        ranked_neighbors = []
        for neighbor in lastfm.similar_artists(anchor, limit=50):
            match = float(neighbor.get("match") or 0)
            if match < 0.10:
                stats["artist_low_similarity"] += 1
                continue
            name = str(neighbor.get("name") or "").strip()
            if not name:
                continue
            style_score, overlap = _neighbor_style_score(anchor_styles, name)
            specific = [tag for tag in overlap if _style_key(tag) not in _GENERIC_STYLE_TAGS]
            if anchor_styles and not (specific or len(overlap) >= 2 or match >= 0.65):
                stats["artist_style_rejected"] += 1
                continue
            ranked_neighbors.append((match + style_score, match, name, overlap))
            stats["eligible_artists"] += 1
        ranked_neighbors.sort(key=lambda row: row[0], reverse=True)
        neighbors = []
        for index in range(0, len(ranked_neighbors), 8):
            band = ranked_neighbors[index:index + 8]
            rng.shuffle(band)
            neighbors.extend(band)
        # Cap top-track requests to avoid long discovery stalls.
        for _combined, match, name, overlap in neighbors[:35]:
            if len(pool) >= max_pool:
                break
            try:
                titles = list(lastfm.top_tracks(name, limit=15))
            except (requests.RequestException, RuntimeError, ValueError):
                continue
            stats["queried_artists"] += 1
            rng.shuffle(titles)
            for title in titles[:3]:
                add(name, title, f"style-matched neighbor of {anchor}", match, overlap)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"[Tune Raider] artist-neighbor discovery unavailable: {exc}", flush=True)

    if _debug():
        print(f"[Tune Raider] discovery source funnel: pool={len(pool)}/{max_pool} "
              f"counters={dict(stats)}", flush=True)
    return _novelty_order(pool, prompt, limit=limit)


def external_candidates_with_prompt_anchor(plan: dict, local_candidates: list[dict], excluded_tracks=None) -> list[dict]:
    existing = list(_original_external_candidates(plan, local_candidates, excluded_tracks) or [])
    anchor = _prompt_anchor_artist.get().strip()
    budget = max(0, tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT)
    if not anchor or budget == 0:
        return _novelty_order(existing, _active_discovery_prompt.get(), limit=budget) if budget else existing

    direct_budget = min(28, max(8, int(round(budget * 0.50))))
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
        f"[Tune Raider] prompt anchor {anchor!r}: reserved {len(direct)} style-matched external candidates",
        flush=True,
    )
    return _novelty_order(merged, _active_discovery_prompt.get(), limit=budget)


def _discovery_first_result(prompt: str, generated: dict, excluded_tracks=None) -> dict:
    """Keep local-library picks as a minority reference for like-artist discovery."""
    anchor = _prompt_anchor_artist.get().strip()
    if not anchor:
        return generated

    tracks = list(generated.get("tracks") or [])
    if not tracks:
        return generated

    styles = _anchor_style_profile(anchor)
    anchor_key = _normalize(anchor)
    target = min(tone_raider.PLAYLIST_TRACK_LIMIT, max(len(tracks), 10))
    max_local = max(2, int(round(target * 0.30)))

    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    local_count = 0
    dropped = 0

    for track in tracks:
        artist = str(track.get("artist") or "").strip()
        title = str(track.get("title") or "").strip()
        key = (_normalize(artist), _normalize(title))
        if not key[0] or not key[1] or key in seen:
            continue

        source = str(track.get("source") or "")
        is_anchor = _normalize(artist) == anchor_key
        close_enough, _overlap = _style_match(styles, artist)

        # Reject off-style tracks from any source. The local library in particular
        # must not be treated as a reason to keep a weak match.
        if not is_anchor and styles and not close_enough:
            dropped += 1
            continue
        if source == "local" and not is_anchor:
            if local_count >= max_local:
                dropped += 1
                continue
            local_count += 1

        seen.add(key)
        kept.append(track)

    # Refill from fresh external, style-matched candidates instead of reaching back
    # into the user's library. This is the expansion step: familiar music guides the
    # search, while the final list is allowed to discover outside it.
    if len(kept) < target:
        refill = _direct_similarity_candidates(
            anchor,
            excluded_tracks,
            limit=max(24, target * 3),
        )
        artist_counts: dict[str, int] = {}
        for track in kept:
            artist_key = _normalize(track.get("artist"))
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1

        for track in refill:
            if len(kept) >= target:
                break
            key = (_normalize(track.get("artist")), _normalize(track.get("title")))
            if not key[0] or not key[1] or key in seen:
                continue
            if artist_counts.get(key[0], 0) >= tone_raider.PLAYLIST_ARTIST_LIMIT:
                continue
            seen.add(key)
            artist_counts[key[0]] = artist_counts.get(key[0], 0) + 1
            kept.append(track)

    if kept:
        generated["tracks"] = kept[:tone_raider.PLAYLIST_TRACK_LIMIT]
    if dropped:
        print(
            f"[Tune Raider] discovery-first anchor filter: dropped {dropped} off-style/library-heavy picks; "
            f"kept {len(generated.get('tracks') or [])} tracks with at most {max_local} local reference tracks",
            flush=True,
        )
    return generated


def ask_for_hybrid_playlist_with_prompt_anchor(prompt: str, excluded_tracks=None) -> dict:
    anchor = _prompt_artist_name(prompt) or ""
    token = _prompt_anchor_artist.set(anchor)
    prompt_token = _active_discovery_prompt.set(prompt)
    original_local_limit = tone_raider.OLLAMA_LOCAL_CANDIDATE_LIMIT
    original_external_limit = tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT
    try:
        if anchor:
            # For explicit discovery-from-an-artist prompts, invert the old 60-local /
            # 20-external balance. The library becomes a reference sample, while the
            # larger share of the curator pool is genuinely new music.
            tone_raider.OLLAMA_LOCAL_CANDIDATE_LIMIT = min(original_local_limit, 24)
            tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT = max(original_external_limit, 36)
        generated = _original_ask_for_hybrid_playlist(prompt, excluded_tracks)
        return _discovery_first_result(prompt, generated, excluded_tracks)
    finally:
        tone_raider.OLLAMA_LOCAL_CANDIDATE_LIMIT = original_local_limit
        tone_raider.OLLAMA_EXTERNAL_CANDIDATE_LIMIT = original_external_limit
        _active_discovery_prompt.reset(prompt_token)
        _prompt_anchor_artist.reset(token)


tone_raider.enrich_library_plan = enrich_library_plan_with_anchor_styles
tone_raider.lastfm_external_candidates = external_candidates_with_prompt_anchor
tone_raider.ask_for_hybrid_playlist = ask_for_hybrid_playlist_with_prompt_anchor
