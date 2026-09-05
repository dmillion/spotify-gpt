#!/usr/bin/env python3
"""Create Spotify playlists from simple artist/title lists using OAuth PKCE."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterable

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
REDIRECT_URI = os.environ.get(
    "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
).strip()
SCOPES = "playlist-modify-private playlist-modify-public"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

DEFAULT_TOKEN_FILE = Path.home() / ".cache" / "spotify-gpt" / "token.json"
TOKEN_FILE = Path(os.environ.get("SPOTIFY_TOKEN_FILE", DEFAULT_TOKEN_FILE)).expanduser()


@dataclass(frozen=True)
class TrackRequest:
    artist: str
    title: str


class SpotifyError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Spotify playlist from an Artist | Title text file."
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
        help="Spotify playlist name",
    )
    parser.add_argument(
        "--description",
        default=(
            "Slow, filthy, riff-forward sludge with grind/hardcore DNA: "
            "Agoraphobic Nosebleed, Pig Destroyer, Beggar-adjacent territory."
        ),
        help="Spotify playlist description",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Create a public playlist (default is private)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve tracks but do not create a playlist",
    )
    return parser.parse_args()


def load_track_requests(path: Path) -> list[TrackRequest]:
    if not path.exists():
        raise SpotifyError(f"Track list not found: {path}")

    tracks: list[TrackRequest] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "|" not in line:
            raise SpotifyError(
                f"{path}:{line_number}: expected 'Artist | Title', got: {raw_line}"
            )

        artist, title = (part.strip() for part in line.split("|", 1))
        if not artist or not title:
            raise SpotifyError(
                f"{path}:{line_number}: both artist and title are required"
            )
        tracks.append(TrackRequest(artist=artist, title=title))

    if not tracks:
        raise SpotifyError(f"No tracks found in {path}")
    return tracks


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def save_token(token: dict) -> None:
    token = dict(token)
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600)) - 60
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def refresh_access_token(token: dict) -> dict | None:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": CLIENT_ID,
        },
        timeout=30,
    )

    if response.status_code == 400:
        try:
            error = response.json().get("error")
        except ValueError:
            error = None
        if error == "invalid_grant":
            TOKEN_FILE.unlink(missing_ok=True)
            return None

    response.raise_for_status()
    refreshed = response.json()
    refreshed.setdefault("refresh_token", token["refresh_token"])
    save_token(refreshed)
    return refreshed


def _redirect_parts() -> tuple[str, int, str]:
    parsed = urllib.parse.urlparse(REDIRECT_URI)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "[::1]", "::1"}:
        raise SpotifyError(
            "SPOTIFY_REDIRECT_URI must be an HTTP loopback address, e.g. "
            "http://127.0.0.1:8888/callback"
        )
    port = parsed.port or 80
    return parsed.hostname or "127.0.0.1", port, parsed.path or "/"


def authorize() -> dict:
    host, port, callback_path = _redirect_parts()
    verifier = _b64url(os.urandom(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [None])[0] != state:
                result["error"] = "OAuth state mismatch"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization failed: state mismatch.")
                return

            if "error" in params:
                result["error"] = params["error"][0]
            elif "code" in params:
                result["code"] = params["code"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Spotify authorization complete.</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    auth_url = f"{AUTH_URL}?{query}"

    print("Opening Spotify authorization in your browser...")
    print(f"If the browser does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer((host, port), CallbackHandler)
    server.timeout = 180
    try:
        server.handle_request()
    finally:
        server.server_close()

    if "error" in result:
        raise SpotifyError(f"Spotify authorization failed: {result['error']}")
    if "code" not in result:
        raise SpotifyError("Timed out waiting for Spotify authorization.")

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    save_token(token)
    return token


def get_access_token() -> str:
    token = load_token()
    if token and token.get("access_token") and token.get("expires_at", 0) > time.time():
        return token["access_token"]

    if token and token.get("refresh_token"):
        refreshed = refresh_access_token(token)
        if refreshed:
            return refreshed["access_token"]

    return authorize()["access_token"]


def api_request(method: str, path: str, token: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {token}"

    for attempt in range(3):
        response = requests.request(
            method,
            f"{API_BASE}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        if response.status_code != 429:
            response.raise_for_status()
            return response

        retry_after = int(response.headers.get("Retry-After", "1"))
        if attempt == 2:
            raise SpotifyError(
                f"Spotify rate limit reached. Retry after {retry_after} seconds."
            )
        time.sleep(min(retry_after, 30))

    raise SpotifyError("Unexpected Spotify API retry failure")


def normalize(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def track_score(track: dict, requested: TrackRequest) -> float:
    title_score = similarity(track.get("name", ""), requested.title)
    artist_names = [artist.get("name", "") for artist in track.get("artists", [])]
    artist_score = max(
        (similarity(name, requested.artist) for name in artist_names),
        default=0.0,
    )
    return (title_score * 0.6) + (artist_score * 0.4)


def search_track(token: str, requested: TrackRequest) -> dict | None:
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
            params={"q": query, "type": "track", "limit": 10},
        )
        for item in response.json().get("tracks", {}).get("items", []):
            if item.get("id"):
                candidates[item["id"]] = item

        if candidates and max(track_score(t, requested) for t in candidates.values()) >= 0.95:
            break

    if not candidates:
        return None

    best = max(candidates.values(), key=lambda track: track_score(track, requested))
    return best if track_score(best, requested) >= 0.72 else None


def create_playlist(token: str, name: str, description: str, public: bool) -> dict:
    response = api_request(
        "POST",
        "/me/playlists",
        token,
        json={"name": name, "description": description, "public": public},
    )
    return response.json()


def add_items(token: str, playlist_id: str, uris: Iterable[str]) -> None:
    uri_list = list(uris)
    for start in range(0, len(uri_list), 100):
        api_request(
            "POST",
            f"/playlists/{playlist_id}/items",
            token,
            json={"uris": uri_list[start : start + 100]},
        )


def main() -> int:
    args = parse_args()

    if not CLIENT_ID:
        raise SpotifyError(
            "SPOTIFY_CLIENT_ID is not set. Copy .env.example to .env and add your Client ID."
        )

    requested_tracks = load_track_requests(Path(args.input))
    token = get_access_token()

    found: list[dict] = []
    missing: list[TrackRequest] = []

    for requested in requested_tracks:
        track = search_track(token, requested)
        if not track:
            missing.append(requested)
            print(f"MISSING {requested.artist} - {requested.title}")
            continue

        found.append(track)
        artists = ", ".join(artist["name"] for artist in track.get("artists", []))
        score = track_score(track, requested)
        print(f"FOUND   {artists} - {track['name']}  [{score:.0%} match]")

    if not found:
        raise SpotifyError("No tracks were resolved; playlist was not created.")

    print(f"\nResolved {len(found)}/{len(requested_tracks)} tracks.")
    if args.dry_run:
        print("Dry run: no playlist created.")
        return 0

    playlist = create_playlist(
        token,
        name=args.name,
        description=args.description,
        public=args.public,
    )
    add_items(token, playlist["id"], [track["uri"] for track in found])

    print(f"\nCreated: {playlist['external_urls']['spotify']}")
    print(f"Added {len(found)} tracks.")

    if missing:
        print("\nCould not confidently resolve:")
        for requested in missing:
            print(f"  - {requested.artist} - {requested.title}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SpotifyError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
