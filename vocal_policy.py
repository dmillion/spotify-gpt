"""Conservative track-level instrumental policy; model guesses are not evidence.

Metadata can be incomplete or wrong. Unknown/conflicting tracks are excluded for
strict requests. This does not claim to perform audio-level vocal detection.
"""
from __future__ import annotations

import re
from functools import lru_cache

import requests
import lastfm_client as lastfm
import musicbrainz_client as musicbrainz
import instrumental_web_evidence
import lrclib_client


def normalize(value):
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(value or '').casefold()).split())


def requires_instrumental(prompt: str) -> bool:
    text = str(prompt or '').casefold()
    # Do not treat a quoted song title as a listening constraint.
    text = re.sub(r'(["“]).*?["”]', ' ', text)
    text = re.sub(r"(?<!\w)'[^']+'(?!\w)", ' ', text)
    # Remove explicit negations and optional preferences before detecting strict intent.
    text = re.sub(r"\b(?:do not|don't|not)\s+(?:avoid|exclude)\s+(?:vocals?|singing|voices?|lyrics)\b", ' ', text)
    text = re.sub(r'\b(?:not|not necessarily|mostly|preferably|prefer|some|avoid|exclude)\s+(?:strictly\s+|only\s+)?instrumentals?\b', ' ', text)
    return bool(re.search(
        r'\binstrumentals?\s*(?:[- ]only|tracks? only|songs? only)\b|'
        r'\b(?:only|strictly|all|entirely|exclusively)\s+instrumentals?\b|'
        r'\b(?:no|without|exclude|avoid)\s+(?:any\s+)?(?:vocals?|singing|voices?|lyrics)\b|'
        r'\bvocal[- ]free\b', text))


def guidance(prompt: str) -> str:
    if not requires_instrumental(prompt):
        return ''
    return (' HARD REQUIREMENT: instrumental only, with no singing, spoken vocals, or vocal samples. '
            'Search for instrumental recordings in the requested style. An instrumental artist can still have vocal songs. '
            'Artist similarity and instrumental passages do not establish that a whole track is instrumental. '
            'Prefer fewer eligible tracks; never relax this requirement to fill slots or include the inspiration artist. ')


def _lastfm_evidence(artist, title):
    if not lastfm.API_KEY:
        return None
    payload = lastfm.call('track.getTopTags', artist=artist, track=title, autocorrect=0)
    block = payload.get('toptags') or {}
    tags = block.get('tag') or []
    if not isinstance(tags, list):
        return None
    strong = set()
    for tag in tags:
        try:
            if float(tag.get('count', 0)) >= 20:
                strong.add(normalize(tag.get('name')))
        except (TypeError, ValueError):
            continue
    if strong & {'vocals', 'vocal', 'male vocals', 'female vocals', 'spoken word', 'vocal samples'}:
        return {'status':'vocal', 'source':'Last.fm track tags'}
    if strong & {'instrumental', 'instrumental rock', 'instrumental metal', 'instrumental stoner rock', 'no vocals'}:
        return {'status':'instrumental', 'source':'Last.fm track tags'}
    return None


def _musicbrainz_evidence(artist, title):
    if not musicbrainz.ENABLED:
        return None
    # Search syntax must never interpret track text as an extra query clause.
    safe = lambda text: re.sub(r'[^\w\s]', ' ', text)
    result = musicbrainz._request('recording/', query=f'recording:"{safe(title)}" AND artist:"{safe(artist)}"', limit=5)
    matches = [r for r in result.get('recordings', [])
               if normalize(r.get('title')) == normalize(title)
               and any(normalize(a.get('artist', {}).get('name')) == normalize(artist)
                       for a in r.get('artist-credit', []) if isinstance(a, dict))]
    supported = None
    for row in matches[:2]:
        recording = musicbrainz._request('recording/' + row['id'], inc='artist-rels+work-rels')
        relations = recording.get('relations', [])
        source = 'https://musicbrainz.org/recording/' + row['id']
        if any(r.get('type') == 'vocal' for r in relations):
            return {'status':'vocal', 'source':source}
        performances = [r for r in relations if r.get('type') == 'performance' and r.get('work')]
        states = []
        for rel in performances:
            if 'instrumental' in rel.get('attributes', []):
                states.append('instrumental')
                continue
            work = rel['work']
            if 'languages' not in work and 'language' not in work:
                work = musicbrainz._request('work/' + work['id'])
            languages = work.get('languages') or ([work['language']] if work.get('language') else [])
            states.append('instrumental' if languages == ['zxx'] else 'unknown')
        if states and all(state == 'instrumental' for state in states):
            supported = {'status':'instrumental', 'source':source}
    return supported


@lru_cache(maxsize=2048)
def track_evidence(artist: str, title: str) -> dict:
    """Missing metadata never implies instrumental. Lookup failures are not cached."""
    # Explicit version labels are track-level evidence; a song simply named
    # 'Instrumental' or an instrumental artist/album tag is not sufficient.
    if re.search(r'(?:\(|\[| - )instrumental(?: version| mix)?(?:\)|\])?\s*$', title, re.I):
        return {'status':'instrumental', 'source':'explicit instrumental version label'}
    evidence = _lastfm_evidence(artist, title)
    if evidence and evidence['status'] == 'vocal':
        return evidence
    recording_evidence = _musicbrainz_evidence(artist, title)
    if recording_evidence and recording_evidence['status'] == 'vocal':
        return recording_evidence
    if recording_evidence or evidence:
        return recording_evidence or evidence
    try:
        online = instrumental_web_evidence.search_instrumental(artist, title)
    except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
        online = None
    return online or {'status':'unknown', 'source':'no track-level evidence'}


def filter_tracks(prompt: str, tracks: list[dict], *, resolved=False):
    if not requires_instrumental(prompt):
        return tracks, []
    accepted, rejected = [], []
    for track in tracks:
        artists = track.get('artists') or []
        artist = str((artists[0].get('name') if artists else '') if resolved else track.get('artist') or '')
        title = str(track.get('name') if resolved else track.get('title') or '')
        try:
            evidence = track_evidence(artist, title)
        except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
            evidence = {'status':'unknown', 'source':'metadata lookup unavailable'}
        # LRCLIB supplies a recording-specific instrumental flag. Re-check
        # resolved Spotify identity using album and duration when available.
        album = track.get('album') if resolved else track.get('album')
        if isinstance(album, dict):
            album = album.get('name')
        duration = track.get('duration_ms')
        if duration is not None:
            duration = float(duration) / 1000.0
        else:
            duration = track.get('duration_seconds')
        lrclib = None
        if evidence['status'] == 'unknown':
            try:
                lrclib = lrclib_client.evidence(artist, title, album, duration)
            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
                lrclib = None
        if lrclib and lrclib['status'] == 'vocal':
            evidence = lrclib
        elif lrclib and lrclib['status'] == 'instrumental' and evidence['status'] == 'unknown':
            evidence = lrclib
        if evidence['status'] == 'instrumental':
            accepted.append({**track, 'instrumental_evidence':evidence})
        else:
            rejected.append(f'{artist} - {title} ({evidence["status"]})')
    if rejected:
        print(f'[Tune Raider] instrumental-only filter: kept {len(accepted)}, excluded {len(rejected)} vocal/unverified tracks', flush=True)
    return accepted, rejected


def enforce_resolved(prompt, tracks):
    accepted, rejected = filter_tracks(prompt, tracks, resolved=True)
    if requires_instrumental(prompt) and not accepted:
        raise ValueError('Instrumental-only request: no Spotify matches had supporting track-level instrumental metadata. No tracks were written. Try a different instrumental reference; unknown tracks are not used as filler.')
    return accepted, rejected
