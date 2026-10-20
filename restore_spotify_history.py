#!/usr/bin/env python3
"""Rebuild missing Tune Raider history from existing Spotify playlists.

Default is a non-destructive preview. Use --apply to insert missing rows.
Uses playlist names supplied in a local text file, not every Spotify playlist.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import spotify_playlist as spotify
from playlist_prompt_metadata import extract_prompt

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("PLAYLIST_HISTORY_DB", ROOT / "data" / "playlist_history.db"))


def playlist_id(url):
    path = urlsplit(str(url or "")).path
    return path.split("/playlist/", 1)[1].split("/", 1)[0] if "/playlist/" in path else ""


def pages(token, path, page_size=50):
    offset = 0
    while True:
        data = spotify.api_request("GET", path, token, params={"limit": page_size, "offset": offset}).json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise RuntimeError(f"Incomplete Spotify response for {path}; no changes made")
        items = data["items"]
        for item in items:
            if isinstance(item, dict):
                yield item
        offset += len(items)
        total = data.get("total")
        if not items or (isinstance(total, int) and offset >= total):
            break


def read_names(file):
    names = [line.strip() for line in file.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not names:
        raise ValueError("Selection file is empty")
    return names


def matches(name, patterns):
    # A trailing ellipsis means the screenshot truncated the display name.
    for pattern in patterns:
        if pattern.endswith("...") or pattern.endswith("…"):
            if name.casefold().startswith(pattern.rstrip("…").rstrip(".").casefold()):
                return True
        elif name.casefold() == pattern.casefold():
            return True
    return False


def build_row(token, playlist):
    pid = playlist["id"]
    # Fetch the full object because list responses can omit description.
    detail = spotify.api_request("GET", f"/playlists/{pid}", token).json()
    description = str(detail.get("description") or "")
    prompt = extract_prompt(description) or ""
    tracks = []
    for entry in pages(token, f"/playlists/{pid}/items"):
        item = entry.get("item") or entry.get("track") or {}
        if not isinstance(item, dict) or item.get("type") not in (None, "track"):
            continue
        name = item.get("name")
        if not name:
            continue
        tracks.append({
            "artist": ", ".join(a.get("name", "") for a in item.get("artists") or []),
            "title": name,
            "url": (item.get("external_urls") or {}).get("spotify"),
        })
    created = datetime.now(timezone.utc).isoformat()
    return (prompt, str(detail.get("name") or playlist.get("name") or ""),
            description, json.dumps(tracks),
            f"https://open.spotify.com/playlist/{pid}", created, "spotify_import", json.dumps([]))


def run(names_file, target, apply):
    if not target.is_file():
        raise FileNotFoundError(f"Database missing: {target}")
    patterns = read_names(names_file)
    with sqlite3.connect(target) as db:
        existing = {playlist_id(row[0]) for row in
                    db.execute("SELECT spotify_url FROM generated_playlists") if playlist_id(row[0])}
    token_info = spotify.load_token()
    if not token_info or not spotify.token_has_required_scopes(token_info):
        raise RuntimeError("Spotify cached token missing or lacks playlist-read-private; authorize through Tune Raider first")
    token = token_info.get("access_token")
    if not token:
        raise RuntimeError("Spotify cached access token missing")
    remote = list(pages(token, "/me/playlists"))
    selected = [p for p in remote if p.get("id") and matches(str(p.get("name") or ""), patterns)]
    selected_ids = {p["id"] for p in selected}
    missing = [p for p in selected if p["id"] not in existing]
    print(f"Spotify playlists listed: {len(remote)}; selected: {len(selected)}; missing locally: {len(missing)}")
    for p in missing:
        print(f"  + {p.get('name')} [{p['id']}]")
    unmatched = [n for n in patterns if not any(matches(p.get("name", ""), [n]) for p in selected)]
    if unmatched:
        print("Names not found on Spotify: " + "; ".join(unmatched))
    if not apply:
        print("Dry run: no changes. Run again with --apply to import these playlists.")
        return
    if not missing:
        print("Nothing to import.")
        return
    # Fetch everything first. Any remote error aborts before SQLite is changed.
    rows = [build_row(token, p) for p in missing]
    backup = target.with_name(target.stem + ".before-spotify-import-" +
                              datetime.now().strftime("%Y%m%d-%H%M%S") + target.suffix)
    with sqlite3.connect(f"file:{target.resolve()}?mode=ro", uri=True) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
        if saved.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Safety backup integrity check failed")
    count = 0
    with sqlite3.connect(target) as db:
        db.execute("BEGIN IMMEDIATE")
        for row in rows:
            pid = playlist_id(row[4])
            if any(playlist_id(x[0]) == pid for x in db.execute("SELECT spotify_url FROM generated_playlists")):
                continue
            db.execute(
                "INSERT INTO generated_playlists (prompt,name,description,tracks,spotify_url,created_at,source,source_tracks) "
                "VALUES (?,?,?,?,?,?,?,?)", row)
            count += 1
    print(f"Imported {count} playlists. Original database safety copy: {backup}")
    print("Original prompts are blank unless stored in Spotify description. Imported timestamps reflect recovery time.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names-file", type=Path, default=ROOT / "recovery_playlist_names.txt")
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(args.names_file.expanduser(), args.db.expanduser(), args.apply)


if __name__ == "__main__":
    main()
