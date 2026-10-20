#!/usr/bin/env python3
"""Recover missing Tune Raider history rows from an older SQLite backup.

Does not overwrite existing playlists. Source is opened read-only and history
is deduplicated by Spotify playlist ID/URL. Makes an automatic destination
backup before modifying anything.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "playlist_history.db"


def playlist_id(url):
    path = urlsplit(str(url or "")).path
    if "/playlist/" in path:
        return path.split("/playlist/", 1)[1].split("/", 1)[0]
    return ""


def connect(path, *, readonly=False):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro" if readonly else str(path), uri=readonly)
    connection.row_factory = sqlite3.Row
    return connection


def recover(source, target, *, apply=False):
    if source.resolve() == target.resolve():
        raise ValueError("Source and target must differ")
    if not source.is_file() or not target.is_file():
        raise FileNotFoundError("Both the old backup and the current history database must exist")
    with connect(source, readonly=True) as old, connect(target, readonly=True) as current:
        if old.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Source backup failed SQLite integrity check")
        cols = {row["name"] for row in current.execute("PRAGMA table_info(generated_playlists)")}
        oldcols = {row["name"] for row in old.execute("PRAGMA table_info(generated_playlists)")}
        columns = [c for c in ("prompt", "name", "description", "tracks", "spotify_url",
                              "created_at", "source", "source_tracks") if c in cols and c in oldcols]
        existing = current.execute("SELECT spotify_url FROM generated_playlists").fetchall()
        existing_urls = {str(row["spotify_url"] or "").strip() for row in existing}
        existing_ids = {playlist_id(url) for url in existing_urls if playlist_id(url)}
        rows = old.execute("SELECT * FROM generated_playlists ORDER BY id").fetchall()
        missing = []
        seen_urls, seen_ids = set(), set()
        for row in rows:
            url = str(row["spotify_url"] or "").strip()
            pid = playlist_id(url)
            if (url and url in existing_urls) or (pid and pid in existing_ids):
                continue
            if (url and url in seen_urls) or (pid and pid in seen_ids):
                continue
            # For no Spotify URL, preserve rows cautiously only when unique
            # by their original generated content.
            if not url:
                signature = (row["prompt"], row["name"], row["created_at"])
                if any((r["prompt"], r["name"], r["created_at"]) == signature for r in missing):
                    continue
                signatures = current.execute(
                    "SELECT 1 FROM generated_playlists WHERE prompt=? AND name=? AND created_at=? LIMIT 1",
                    signature,
                ).fetchone()
                if signatures:
                    continue
            missing.append(row)
            if url:
                seen_urls.add(url)
            if pid:
                seen_ids.add(pid)
        print(f"Old backup rows: {len(rows)}; missing from current database: {len(missing)}")
        for row in missing:
            print(f"  + {row['name']} | {row['spotify_url'] or '(no Spotify URL)'}")
        if not apply or not missing:
            print("Dry run only. Add --apply to merge the missing rows.")
            return len(missing)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safety = target.with_name(target.stem + ".before-recovery-" + stamp + target.suffix)
    with connect(target, readonly=True) as current, sqlite3.connect(safety) as saved:
        current.backup(saved)
        if saved.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Safety backup failed validation")
    with connect(target) as destination:
        destination.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in columns)
        statement = f"INSERT INTO generated_playlists ({','.join(columns)}) VALUES ({placeholders})"
        for row in missing:
            destination.execute(statement, [row[c] for c in columns])
        destination.commit()
    print(f"Restored {len(missing)} records. Safety backup: {safety}")
    return len(missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_backup", type=Path)
    parser.add_argument("--target", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="Merge missing records (default: dry run)")
    args = parser.parse_args()
    recover(args.old_backup.expanduser(), args.target.expanduser(), apply=args.apply)


if __name__ == "__main__":
    main()
