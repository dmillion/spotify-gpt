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
        "--description",
        default=None,
        help="Spotify playlist description; overrides '# Description:' metadata in the source file",
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


def get_playlist(token: str, playlist_id: str) -> dict:
    return spotify.api_request(
        "GET",
        f"/playlists/{playlist_id}",
        token,
    ).json()


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


def update_description(token: str, playlist_id: str, description: str) -> None:
    spotify.api_request(
        "PUT",
        f"/playlists/{playlist_id}",
        token,
        json={"description": description},
    )


def main() -> int:
    args = parse_args()

    if not spotify.CLIENT_ID:
        raise spotify.SpotifyError(
            "SPOTIFY_CLIENT_ID is not set. Add it to .env before running sync."
        )

    source_path = Path(args.input)
    requested_tracks = spotify.load_track_requests(source_path)
    source_description = spotify.load_playlist_description(source_path)
    desired_description = args.description if args.description is not None else source_description
    token = get_scoped_token()

    if args.playlist_id:
        playlist = get_playlist(token, args.playlist_id)
        playlist_id = args.playlist_id
        playlist_name = playlist.get("name", args.name)
    else:
        playlist = find_playlist(token, args.name)
        if not playlist:
            raise spotify.SpotifyError(
                f"Could not find a Spotify playlist named {args.name!r}."
            )
        playlist_id = playlist["id"]
        playlist_name = playlist.get("name", args.name)

    current_description = playlist.get("description") or ""
    description_changed = (
        desired_description is not None and desired_description != current_description
    )

    existing_uris = get_existing_uris(token, playlist_id)
    existing_set = set(existing_uris)
    resolved: list[dict] = []
    additions: list[dict] = []
    missing = []

    print(f"Playlist: {playlist_name} ({len(existing_uris)} existing items)")
    if desired_description is not None:
        status = "UPDATE" if description_changed else "KEEP"
        print(f"{status} description: {desired_description}")
    else:
        print("KEEP description: no # Description: metadata in source file")
    print()

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
        f"Unresolved: {len(missing)} | Description: {'update' if description_changed else 'keep'}"
    )

    if args.exact and missing:
        print("\nWARNING: --exact will omit unresolved source tracks from Spotify.")

    if args.dry_run:
        if args.exact:
            print("Dry run: exact sync would replace playlist contents with the resolved source order.")
        else:
            print("Dry run: add-only sync would not modify playlist tracks.")
        if description_changed:
            print("Dry run: playlist description would also be updated.")
        return 0

    if description_changed:
        update_description(token, playlist_id, desired_description)
        print(f"Updated description for {playlist_name!r}.")

    if args.exact:
        replace_items(token, playlist_id, desired_uris)
        print(f"Replaced contents of {playlist_name!r} with {len(desired_uris)} resolved tracks.")
    elif additions:
        spotify.add_items(token, playlist_id, [track["uri"] for track in additions])
        print(f"Added {len(additions)} tracks to {playlist_name!r}.")
    else:
        print("Playlist tracks are already up to date for add-only sync.")

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
