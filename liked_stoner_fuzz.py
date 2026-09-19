#!/usr/bin/env python3
"""Build a stoner/fuzz-rock playlist from the current user's Spotify Liked Songs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

import spotify_playlist as spotify

REQUIRED_SCOPES = {
    "user-library-read",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
}

DEFAULT_NAME = "Fuzzed & Fried"
DEFAULT_OUTPUT = Path("playlists/liked-stoner-fuzz.txt")
DEFAULT_DESCRIPTION = (
    "Sun-baked speakers, blown cones, hot asphalt, and riffs thick enough to leave fingerprints."
)

# Strong signals are intentionally narrow so this does not turn into a generic hard-rock playlist.
GENRE_WEIGHTS = {
    "stoner rock": 5,
    "stoner metal": 5,
    "fuzz rock": 5,
    "desert rock": 5,
    "heavy psych": 4,
    "psychedelic doom": 4,
    "doom metal": 2,
    "sludge metal": 2,
    "southern metal": 2,
    "psychedelic rock": 1,
    "garage rock": 1,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan Spotify Liked Songs and build a conservative stoner/fuzz-rock playlist."
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="Spotify playlist name")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Playlist source file to write (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=2,
        help="Minimum genre-match score (default: 2; raise for a stricter playlist)",
    )
    parser.add_argument("--public", action="store_true", help="Make a newly created playlist public")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without writing or changing Spotify")
    return parser.parse_args()


def get_scoped_token() -> str:
    spotify.SCOPES = " ".join(sorted(REQUIRED_SCOPES))
    cached = spotify.load_token()
    granted = set((cached or {}).get("scope", "").split())
    if cached and not REQUIRED_SCOPES.issubset(granted):
        print("Spotify authorization needs access to Liked Songs; reauthorizing once...")
        spotify.TOKEN_FILE.unlink(missing_ok=True)
    return spotify.get_access_token()


def get_liked_tracks(token: str) -> list[dict]:
    tracks: list[dict] = []
    offset = 0
    while True:
        response = spotify.api_request(
            "GET",
            "/me/tracks",
            token,
            params={"limit": 50, "offset": offset},
        )
        payload = response.json()
        items = payload.get("items", [])
        for row in items:
            track = row.get("track") or {}
            if track.get("uri") and track.get("artists"):
                tracks.append(track)
        if not payload.get("next") or not items:
            break
        offset += len(items)
    return tracks


def get_artist_genres(token: str, artist_ids: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    unique_ids = list(dict.fromkeys(artist_ids))
    for start in range(0, len(unique_ids), 50):
        batch = unique_ids[start : start + 50]
        response = spotify.api_request(
            "GET",
            "/artists",
            token,
            params={"ids": ",".join(batch)},
        )
        for artist in response.json().get("artists", []):
            if artist and artist.get("id"):
                result[artist["id"]] = [g.casefold() for g in artist.get("genres", [])]
    return result


def genre_score(genres: list[str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for genre in genres:
        matched = False
        for needle, weight in GENRE_WEIGHTS.items():
            if needle in genre:
                score += weight
                reasons.append(genre)
                matched = True
                break
        if not matched and ("stoner" in genre or "fuzz" in genre or "desert" in genre):
            score += 4
            reasons.append(genre)
    return score, list(dict.fromkeys(reasons))


def find_playlist(token: str, name: str) -> dict | None:
    offset = 0
    while True:
        response = spotify.api_request(
            "GET",
            "/me/playlists",
            token,
            params={"limit": 50, "offset": offset},
        )
        payload = response.json()
        items = payload.get("items", [])
        for item in items:
            if item.get("name") == name:
                return item
        if not payload.get("next") or not items:
            return None
        offset += len(items)


def replace_items(token: str, playlist_id: str, uris: list[str]) -> None:
    spotify.api_request(
        "PUT",
        f"/playlists/{playlist_id}/items",
        token,
        json={"uris": uris[:100]},
    )
    if len(uris) > 100:
        spotify.add_items(token, playlist_id, uris[100:])


def write_source(path: Path, tracks: list[dict]) -> None:
    lines = [
        f"# {DEFAULT_NAME}",
        f"# Description: {DEFAULT_DESCRIPTION}",
        "# Generated from Spotify Liked Songs by liked_stoner_fuzz.py.",
        "",
    ]
    for track in tracks:
        artist = track["artists"][0]["name"]
        lines.append(f"{artist} | {track['name']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not spotify.CLIENT_ID:
        raise spotify.SpotifyError("SPOTIFY_CLIENT_ID is not set. Add it to .env first.")

    token = get_scoped_token()
    liked = get_liked_tracks(token)
    artist_ids = [
        artist["id"]
        for track in liked
        for artist in track.get("artists", [])
        if artist.get("id")
    ]
    genres_by_artist = get_artist_genres(token, artist_ids)

    matched: list[dict] = []
    seen: set[str] = set()
    print(f"Scanning {len(liked)} liked tracks...\n")

    for track in liked:
        best_score = 0
        best_reasons: list[str] = []
        for artist in track.get("artists", []):
            score, reasons = genre_score(genres_by_artist.get(artist.get("id", ""), []))
            if score > best_score:
                best_score = score
                best_reasons = reasons

        if best_score < args.min_score or track["uri"] in seen:
            continue
        seen.add(track["uri"])
        matched.append(track)
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        reason_text = ", ".join(best_reasons[:3]) or "genre match"
        print(f"KEEP  {artists} - {track['name']}  [{reason_text}]")

    print(f"\nMatched {len(matched)} of {len(liked)} liked tracks.")
    if args.dry_run:
        print("Dry run: no file written and Spotify was not modified.")
        return 0

    if not matched:
        raise spotify.SpotifyError("No stoner/fuzz candidates matched; nothing was created.")

    write_source(args.output, matched)
    print(f"Wrote {args.output}")

    playlist = find_playlist(token, args.name)
    if playlist:
        playlist_id = playlist["id"]
        spotify.api_request(
            "PUT",
            f"/playlists/{playlist_id}",
            token,
            json={"description": DEFAULT_DESCRIPTION},
        )
        replace_items(token, playlist_id, [track["uri"] for track in matched])
        print(f"Updated existing playlist {args.name!r} with {len(matched)} tracks.")
    else:
        playlist = spotify.create_playlist(
            token,
            name=args.name,
            description=DEFAULT_DESCRIPTION,
            public=args.public,
        )
        spotify.add_items(token, playlist["id"], [track["uri"] for track in matched])
        print(f"Created {args.name!r} with {len(matched)} tracks.")
        print(playlist.get("external_urls", {}).get("spotify", ""))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (spotify.SpotifyError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
