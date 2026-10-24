#!/usr/bin/env python3
"""Read-only diagnosis of a saved Spotify playlist's sync status."""
from __future__ import annotations
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

import spotify_playlist as spotify
from spotify_history_reconcile import complete_owned_snapshot

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("PLAYLIST_HISTORY_DB", ROOT / "data" / "playlist_history.db"))


def main():
    supplied = sys.argv[1] if len(sys.argv) > 1 else ""
    path = urlsplit(supplied).path
    playlist_id = path.split("/playlist/")[-1].split("/")[0] if "/playlist/" in path else supplied.strip()
    if not playlist_id.isalnum():
        raise SystemExit("Provide a Spotify playlist ID or URL.")
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        matches = db.execute(
            "SELECT id,name,spotify_url FROM generated_playlists "
            "WHERE spotify_url LIKE ?", ("%/playlist/" + playlist_id + "%",)
        ).fetchall()
    print(f"Playlist ID: {playlist_id}")
    print(f"Local history rows: {[(row['id'], row['name']) for row in matches]}")
    token_info = spotify.load_token()
    if not token_info:
        raise SystemExit("No cached Spotify authorization; sign in through Tune Raider.")
    if not spotify.token_has_required_scopes(token_info):
        raise SystemExit("Spotify token lacks required scopes; reauthorize Tune Raider.")
    ids = complete_owned_snapshot(spotify, token_info["access_token"])
    print(f"Complete Spotify inventory: {len(ids)} playlist IDs")
    print(f"Playlist in Spotify library: {playlist_id in ids}")
    print("No SQLite rows were changed.")


if __name__ == "__main__":
    main()
