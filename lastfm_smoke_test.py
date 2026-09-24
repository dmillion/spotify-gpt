#!/usr/bin/env python3
"""Smoke-test Last.fm artist tags, similar artists, and similar tracks."""

from __future__ import annotations

import sys

import requests

import lastfm_client as lastfm

DEFAULT_ARTISTS = [
    "Weedeater",
    "Brainoil",
    "Stars of the Lid",
]


def main() -> int:
    if not lastfm.API_KEY:
        print("ERROR: LASTFM_API_KEY is not set in .env", file=sys.stderr)
        return 2

    print("Last.fm API key: found")
    print(
        "Last.fm shared secret: "
        + ("found" if lastfm.SHARED_SECRET else "not set (not required for these read-only calls)")
    )

    artists = [arg.strip() for arg in sys.argv[1:] if arg.strip()] or DEFAULT_ARTISTS
    try:
        for artist in artists:
            print(f"\n{artist}")
            raw_tags = lastfm.top_tags(artist)[:12]
            filtered_tags = lastfm.filtered_top_tags(artist, min_weight=5, limit=6)
            tracks = lastfm.top_tracks(artist, limit=5)
            neighbors = lastfm.similar_artists(artist, limit=5)

            print("  raw tags:")
            if raw_tags:
                for name, count in raw_tags:
                    print(f"    - {name} ({count})")
            else:
                print("    - none returned")

            print("  app genre/theme tags:")
            if filtered_tags:
                for tag in filtered_tags:
                    print(f"    - {tag['name']} ({tag['weight']})")
            else:
                print("    - none passed filtering")

            print("  similar artists:")
            if neighbors:
                for neighbor in neighbors:
                    print(f"    - {neighbor['name']} ({neighbor['match']:.3f})")
            else:
                print("    - none returned")

            print("  top tracks:")
            if tracks:
                for track in tracks:
                    print(f"    - {track}")
            else:
                print("    - none returned")

            if tracks:
                seed_track = tracks[0]
                similar_tracks = lastfm.similar_tracks(artist, seed_track, limit=5)
                print(f"  tracks similar to {seed_track}:")
                if similar_tracks:
                    for candidate in similar_tracks:
                        print(
                            f"    - {candidate['artist']} - {candidate['title']} "
                            f"({candidate['match']:.3f})"
                        )
                else:
                    print("    - none returned")
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\nOK: Last.fm tag and similarity endpoints are reachable with this API key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
