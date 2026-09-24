#!/usr/bin/env python3
"""Smoke-test Last.fm API access and print artist/genre-tag data."""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://ws.audioscrobbler.com/2.0/"
API_KEY = os.environ.get("LASTFM_API_KEY", "").strip()
SHARED_SECRET = os.environ.get("LASTFM_SHARED_SECRET", "").strip()

DEFAULT_ARTISTS = [
    "Weedeater",
    "Brainoil",
    "Stars of the Lid",
]


def call(method: str, **params) -> dict:
    response = requests.get(
        API_URL,
        params={
            "method": method,
            "api_key": API_KEY,
            "format": "json",
            "autocorrect": 1,
            **params,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"Last.fm error {payload['error']}: {payload.get('message', 'Unknown error')}")
    return payload


def top_tags(artist: str) -> list[tuple[str, int]]:
    payload = call("artist.getTopTags", artist=artist)
    raw_tags = payload.get("toptags", {}).get("tag", [])
    tags = []
    for item in raw_tags:
        name = str(item.get("name") or "").strip()
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if name:
            tags.append((name, count))
    return tags


def top_tracks(artist: str, limit: int = 5) -> list[str]:
    payload = call("artist.getTopTracks", artist=artist, limit=limit)
    tracks = payload.get("toptracks", {}).get("track", [])
    return [str(track.get("name") or "").strip() for track in tracks if track.get("name")]


def main() -> int:
    if not API_KEY:
        print("ERROR: LASTFM_API_KEY is not set in .env", file=sys.stderr)
        return 2

    print("Last.fm API key: found")
    print(f"Last.fm shared secret: {'found' if SHARED_SECRET else 'not set (not required for these read-only calls)'}")

    artists = [arg.strip() for arg in sys.argv[1:] if arg.strip()] or DEFAULT_ARTISTS
    for artist in artists:
        print(f"\n{artist}")
        tags = top_tags(artist)[:12]
        tracks = top_tracks(artist, limit=5)
        print("  tags:")
        if tags:
            for name, count in tags:
                print(f"    - {name} ({count})")
        else:
            print("    - none returned")
        print("  top tracks:")
        if tracks:
            for track in tracks:
                print(f"    - {track}")
        else:
            print("    - none returned")

    print("\nOK: Last.fm artist and tag endpoints are reachable with this API key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
