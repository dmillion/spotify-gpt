"""Bandcamp discovery references sourced from MusicBrainz artist relationships.

No Bandcamp pages or streams are fetched. MusicBrainz provides verified artist
identity and external links; recordings are MusicBrainz metadata candidates,
subject to the ordinary Spotify resolution step.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import musicbrainz_client as musicbrainz


def bandcamp_links(details):
    links = []
    for rel in details.get("relations") or []:
        if not isinstance(rel, dict) or rel.get("target-type") != "url":
            continue
        url = str((rel.get("url") or {}).get("resource") or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not (
            host == "bandcamp.com" or host.endswith(".bandcamp.com")
        ):
            continue
        if url not in links:
            links.append(url)
    return links


def discover(artists, excluded=(), limit=12, max_artists=3):
    """Explore MusicBrainz recordings for artist seeds with Bandcamp relations.

    Returns only actual MusicBrainz recording titles. A Bandcamp link is context,
    not proof of the recording's sound or existence on Bandcamp.
    """
    excluded_keys = set()
    for entry in excluded:
        artist, sep, title = str(entry).partition(" - ")
        if sep:
            excluded_keys.add((artist.strip().casefold(), title.strip().casefold()))
    result, seen_artists, seen_tracks = [], set(), set()
    for name in artists:
        name = str(name or "").strip()
        if not name or name.casefold() in seen_artists:
            continue
        seen_artists.add(name.casefold())
        if len(seen_artists) > max_artists:
            break
        try:
            details = musicbrainz.artist_details(name)
            links = bandcamp_links(details)
            if not links:
                continue
            recordings = musicbrainz.recordings_by_artist(name, limit=min(8, limit))
        except Exception as exc:
            print(f"[Tune Raider] Bandcamp reference lookup skipped for {name}: {exc}", flush=True)
            continue
        for row in recordings:
            key = (str(row.get("artist") or "").casefold(),
                   str(row.get("title") or "").casefold())
            if key in seen_tracks or key in excluded_keys:
                continue
            seen_tracks.add(key)
            result.append({
                "artist": row["artist"], "title": row["title"],
                "source": "bandcamp-reference",
                "relationship": "MusicBrainz artist with Bandcamp reference",
                "bandcamp_artist_url": links[0],
            })
            if len(result) >= limit:
                return result
    return result
