#!/usr/bin/env python3
"""Sync a track-list file into an existing Spotify playlist."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

import spotify_playlist as spotify

REQUIRED_SCOPES = {
    "playlist-modify-private",
    "playlist-modify-public",
    "playlist-read-private",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync an Artist | Title file into an existing Spotify playlist."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="playlists/sludge-with-grind-brain.txt",
        help="Track list file (default: playlists/sludge-with-grind-brain.txt)",
    )
    parser.add_argument(
        "--name",
        default="Sludge With Grind Brain",
        help="Exact Spotify playlist name to update",
    )
    parser.add_argument(
        "--playlist-id",
        help="Spotify playlist ID; skips lookup by name",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Make the Spotify playlist exactly match the resolved source file, including removals and order",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve tracks and show planned changes without modifying Spotify",
    )
    return parser.parse_args()


def get_scoped_token() -> str:
    spotify.SCOPES = " ".join(sorted(REQUIRED_SCOPES))
    cached = spotify.load_token()
    granted = set((cached or {}).get("scope", "").split())

    if cached and not REQUIRED_SCOPES.issubset(granted):
        print("Spotify authorization needs playlist-read-private; reauthorizing once...")
        spotify.TOKEN_FILE.unlink(missing_ok=True)

    return spotify.get_access_token()


def find_playlist(token: str, name: str) -> dict | None:
    offset = 0
    matches: list[dict] = []

    while True:
        response = spotify.api_request(
            "GET",
            "/me/playlists",
            token,
            params={"limit": 50, "offset": offset},
        )
        payload = response.json()
        items = payload.get("items", [])
        matches.extend(item for item in items if item.get("name") == name)

        if not payload.get("next") or not items:
            break
        offset += len(items)

    if not matches:
        return None
    if len(matches) > 1:
        print(f"WARNING: found {len(matches)} playlists named {name!r}; using the first one.")
    return matches[0]


def get_existing_uris(token: str, playlist_id: str) -> list[str]:
    uris: list[str] = []
    offset = 0

    while True:
        response = spotify.api_request(
            "GET",
            f"/playlists/{playlist_id}/items",
            token,
            params={"limit": 50, "offset": offset},
        )
        payload = response.json()
        rows = payload.get("items", [])

        for row in rows:
            item = row.get("item") or row.get("track") or {}
            uri = item.get("uri")
            if uri:
                uris.append(uri)

        if not payload.get("next") or not rows:
            break
        offset += len(rows)

    return uris


def replace_items(token: str, playlist_id: str, uris: list[str]) -> None:
    first = uris[:100]
    spotify.api_request(
        "PUT",
        f"/playlists/{playlist_id}/items",
        token,
        json={"uris": first},
    )
    if len(uris) > 100:
        spotify.add_items(token, playlist_id, uris[100:])


def main() -> int:
    args = parse_args()

    if not spotify.CLIENT_ID:
        raise spotify.SpotifyError(
            "SPOTIFY_CLIENT_ID is not set. Add it to .env before running sync."
        )

    requested_tracks = spotify.load_track_requests(Path(args.input))
    token = get_scoped_token()

    if args.playlist_id:
        playlist_id = args.playlist_id
        playlist_name = args.name
    else:
        playlist = find_playlist(token, args.name)
        if not playlist:
            raise spotify.SpotifyError(
                f"Could not find a Spotify playlist named {args.name!r}."
            )
        playlist_id = playlist["id"]
        playlist_name = playlist.get("name", args.name)

    existing_uris = get_existing_uris(token, playlist_id)
    existing_set = set(existing_uris)
    resolved: list[dict] = []
    additions: list[dict] = []
    missing = []

    print(f"Playlist: {playlist_name} ({len(existing_uris)} existing items)\n")

    for requested in requested_tracks:
        track = spotify.search_track(token, requested)
        if not track:
            missing.append(requested)
            print(f"MISSING {requested.artist} - {requested.title}")
            continue

        resolved.append(track)
        artists = ", ".join(artist["name"] for artist in track.get("artists", []))
        score = spotify.track_score(track, requested)

        if track["uri"] in existing_set:
            print(f"KEEP    {artists} - {track['name']}")
        else:
            additions.append(track)
            print(f"ADD     {artists} - {track['name']}  [{score:.0%} match]")

    desired_uris = [track["uri"] for track in resolved]
    desired_set = set(desired_uris)
    removals = [uri for uri in existing_uris if uri not in desired_set]

    print(
        f"\nExisting: {len(existing_uris)} | Resolved: {len(resolved)} | "
        f"New: {len(additions)} | Remove: {len(removals) if args.exact else 0} | "
        f"Unresolved: {len(missing)}"
    )

    if args.exact and missing:
        print("\nWARNING: --exact will omit unresolved source tracks from Spotify.")

    if args.dry_run:
        if args.exact:
            print("Dry run: exact sync would replace playlist contents with the resolved source order.")
        else:
            print("Dry run: add-only sync would not modify Spotify.")
        return 0

    if args.exact:
        replace_items(token, playlist_id, desired_uris)
        print(f"Replaced contents of {playlist_name!r} with {len(desired_uris)} resolved tracks.")
    elif additions:
        spotify.add_items(token, playlist_id, [track["uri"] for track in additions])
        print(f"Added {len(additions)} tracks to {playlist_name!r}.")
    else:
        print("Playlist is already up to date for add-only sync.")

    if missing:
        print("\nCould not confidently resolve:")
        for requested in missing:
            print(f"  - {requested.artist} - {requested.title}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (spotify.SpotifyError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
