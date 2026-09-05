#!/usr/bin/env python3
"""Check whether requested Spotify tracks are playable for the authorized account market."""

from __future__ import annotations

import argparse
from pathlib import Path

from spotify_playlist import (
    TrackRequest,
    api_request,
    get_access_token,
    load_track_requests,
    similarity,
)


def candidate_score(track: dict, requested: TrackRequest) -> float:
    title_score = similarity(track.get("name", ""), requested.title)
    artist_names = [artist.get("name", "") for artist in track.get("artists", [])]
    artist_score = max(
        (similarity(name, requested.artist) for name in artist_names),
        default=0.0,
    )
    return (title_score * 0.6) + (artist_score * 0.4)


def search_market_track(token: str, requested: TrackRequest) -> dict | None:
    queries = [
        f'track:"{requested.title}" artist:"{requested.artist}"',
        f"{requested.artist} {requested.title}",
    ]

    candidates: dict[str, dict] = {}
    for query in queries:
        response = api_request(
            "GET",
            "/search",
            token,
            params={
                "q": query,
                "type": "track",
                "limit": 10,
                "market": "from_token",
            },
        )
        for item in response.json().get("tracks", {}).get("items", []):
            if item.get("id"):
                candidates[item["id"]] = item

    if not candidates:
        return None

    return max(candidates.values(), key=lambda track: candidate_score(track, requested))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Spotify playability for tracks in an Artist | Title file."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="playlists/sludge-with-grind-brain.txt",
    )
    args = parser.parse_args()

    token = get_access_token()
    requests = load_track_requests(Path(args.input))

    playable = 0
    for requested in requests:
        track = search_market_track(token, requested)
        if not track:
            print(f"NOT FOUND   {requested.artist} - {requested.title}")
            continue

        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        is_playable = track.get("is_playable")
        restriction = (track.get("restrictions") or {}).get("reason")
        score = candidate_score(track, requested)

        if is_playable is True:
            status = "PLAYABLE"
            playable += 1
        elif is_playable is False:
            status = "BLOCKED"
        else:
            status = "UNKNOWN"

        detail = f" restriction={restriction}" if restriction else ""
        print(
            f"{status:<8} {artists} - {track.get('name', '')} "
            f"[{score:.0%} match]{detail}"
        )

    print(f"\nSpotify reports {playable}/{len(requests)} tracks explicitly playable.")
    print("If all are PLAYABLE but the playlist Play button still does nothing, the issue is client/playback-context rather than catalog availability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
