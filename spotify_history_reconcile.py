"""Conservative Spotify history reconciliation using playlist IDs, never names."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def complete_owned_snapshot(spotify, token):
    """Return playlist IDs only after a complete, internally consistent listing."""
    found = set()
    offset = 0
    total = None
    while True:
        response = spotify.api_request("GET", "/me/playlists", token,
                                       params={"limit": 50, "offset": offset})
        if response.status_code != 200:
            raise ValueError("Spotify playlist listing failed")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("Invalid Spotify playlist listing")
        count = payload.get("total")
        if not isinstance(count, int) or count < 0:
            raise ValueError("Spotify playlist listing omitted total")
        if total is None:
            total = count
        elif total != count:
            raise ValueError("Spotify playlist count changed mid-pagination")
        items = payload["items"]
        if not items and offset < total:
            raise ValueError(f"Spotify returned an empty page at offset {offset} of {total}")
        if len(items) > 50 or offset + len(items) > total:
            raise ValueError("Spotify playlist page exceeds reported total")
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                raise ValueError("Invalid Spotify playlist item")
            found.add(str(item["id"]))
        offset += len(items)
        if offset >= total:
            break
    # A sudden empty list is not authoritative evidence that user deleted everything.
    if not found:
        raise ValueError("Empty Spotify playlist listing; refusing to reconcile deletions")
    if len(found) != total:
        raise ValueError("Spotify playlist listing contained duplicates or missing records")
    return found


def confirm_missing(spotify, token, playlist_id):
    """Return True only for a definite HTTP 404, never for auth/network failures."""
    try:
        spotify.api_request("GET", f"/playlists/{playlist_id}", token)
    except spotify.SpotifyError as exc:
        return str(exc).startswith(f"Spotify API HTTP 404 on GET /playlists/{playlist_id}:")
    return False


def archive_missing(db, rows, spotify, token, playlist_id_from_url):
    """Archive then hide confirmed missing entries in a single SQLite transaction."""
    available = complete_owned_snapshot(spotify, token)
    db.execute(
        "CREATE TABLE IF NOT EXISTS spotify_history_archive "
        "(original_id INTEGER PRIMARY KEY, playlist_id TEXT, archived_at TEXT NOT NULL, "
        "row_data TEXT NOT NULL)"
    )
    absent = [
        row for row in rows
        if (playlist_id_from_url(row["spotify_url"])
            and playlist_id_from_url(row["spotify_url"]) not in available)
    ]
    print(f"[Tune Raider] history inventory: Spotify lists {len(available)} playlists; "
          f"{len(rows)} local linked rows; {len(absent)} missing IDs", flush=True)
    if not absent:
        return 0
    # Removing a playlist from Spotify's library need not make its URL 404.
    # Require a second complete, consistent listing before archiving anything.
    confirmed_available = complete_owned_snapshot(spotify, token)
    if confirmed_available != available:
        raise ValueError("Spotify playlist IDs changed between checks; refusing to archive")
    # Guard against another mass-deletion incident, even on a valid-looking snapshot.
    if len(absent) > 3:
        raise ValueError(f"{len(absent)} playlists appear missing; refusing bulk archive (limit 3 per sync)")
    removed = 0
    for row in absent:
        playlist_id = playlist_id_from_url(row["spotify_url"])
        if not playlist_id or playlist_id in confirmed_available:
            continue
        full = db.execute("SELECT * FROM generated_playlists WHERE id=?", (row["id"],)).fetchone()
        if full is None:
            continue
        db.execute(
            "INSERT OR IGNORE INTO spotify_history_archive "
            "(original_id,playlist_id,archived_at,row_data) VALUES (?,?,?,?)",
            (row["id"], playlist_id, datetime.now(timezone.utc).isoformat(),
             json.dumps(dict(full))),
        )
        db.execute("DELETE FROM generated_playlists WHERE id=?", (row["id"],))
        removed += 1
        print(f"[Tune Raider] archived missing Spotify playlist {playlist_id} (local row {row['id']})", flush=True)
    return removed
