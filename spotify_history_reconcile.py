"""Conservative Spotify history reconciliation using playlist IDs, never names."""
from __future__ import annotations

import json
from collections import defaultdict
from html import unescape
from datetime import datetime, timezone


def complete_owned_snapshot(spotify, token, *, with_names=False):
    """Return playlist IDs only after a complete, internally consistent listing."""
    found = {}
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
            if with_names and not isinstance(item.get("name"), str):
                raise ValueError("Spotify playlist listing omitted a name")
            found[str(item["id"])] = str(item.get("name") or "")
        offset += len(items)
        if offset >= total:
            break
    # A sudden empty list is not authoritative evidence that user deleted everything.
    if not found:
        raise ValueError("Empty Spotify playlist listing; refusing to reconcile deletions")
    if len(found) != total:
        raise ValueError("Spotify playlist listing contained duplicates or missing records")
    return found if with_names else set(found)


def confirm_missing(spotify, token, playlist_id):
    """Return True only for a definite HTTP 404, never for auth/network failures."""
    try:
        spotify.api_request("GET", f"/playlists/{playlist_id}", token)
    except spotify.SpotifyError as exc:
        return str(exc).startswith(f"Spotify API HTTP 404 on GET /playlists/{playlist_id}:")
    return False


def _name(value):
    return " ".join(unescape(str(value or "")).casefold().split())


def archive_missing(db, rows, spotify, token, playlist_id_from_url):
    """Reconcile name counts, preferring missing IDs when duplicate names exist."""
    first = complete_owned_snapshot(spotify, token, with_names=True)
    second = complete_owned_snapshot(spotify, token, with_names=True)
    if first != second or not first:
        raise ValueError("Spotify inventories inconsistent or empty; no history changes")
    remote_by_name = defaultdict(set)
    for playlist_id, name in first.items():
        remote_by_name[_name(name)].add(playlist_id)
    local_by_name = defaultdict(list)
    for row in rows:
        if row["spotify_url"]:
            local_by_name[_name(row["name"])].append(row)
    candidates = []
    for name, local_rows in local_by_name.items():
        remote_ids = remote_by_name.get(name, set())
        excess = len(local_rows) - len(remote_ids)
        if excess <= 0:
            continue
        missing = sorted(
            (row for row in local_rows
             if playlist_id_from_url(row["spotify_url"]) not in remote_ids),
            key=lambda row: row["id"],
        )
        if len(missing) < excess:
            continue
        candidates.extend(missing[:excess])
    print(f"[Tune Raider] history name reconciliation: {len(first)} Spotify playlists, "
          f"{len(rows)} linked rows, {len(candidates)} excess entries", flush=True)
    if len(candidates) > 3:
        raise ValueError("Refusing bulk archive of more than 3 history entries")
    if not candidates:
        return 0
    db.execute(
        "CREATE TABLE IF NOT EXISTS spotify_history_archive "
        "(original_id INTEGER PRIMARY KEY, playlist_id TEXT, archived_at TEXT NOT NULL, "
        "row_data TEXT NOT NULL)"
    )
    removed = 0
    for row in candidates:
        full = db.execute("SELECT * FROM generated_playlists WHERE id=?", (row["id"],)).fetchone()
        if full is None:
            continue
        playlist_id = playlist_id_from_url(row["spotify_url"])
        db.execute(
            "INSERT OR IGNORE INTO spotify_history_archive "
            "(original_id,playlist_id,archived_at,row_data) VALUES (?,?,?,?)",
            (row["id"], playlist_id, datetime.now(timezone.utc).isoformat(),
             json.dumps(dict(full))),
        )
        db.execute("DELETE FROM generated_playlists WHERE id=?", (row["id"],))
        removed += 1
        print(f"[Tune Raider] archived missing {row['name']!r} (Spotify {playlist_id})", flush=True)
    return removed
