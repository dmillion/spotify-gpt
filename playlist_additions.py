"""Append fresh discoveries to a playlist that is already working."""
from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone

import requests
from flask import jsonify, request

import refinement_context
import run_app
from learning_store import record
from preference_policy import artist_blocked
from spotify_playlist_state import (
    as_exclusions,
    compare_stored_to_live,
    ensure_playlist_read_scope,
    fetch_playlist_tracks,
    normalized_key,
)

tr = run_app.tone_raider
ADD_TO_COUNT = max(1, min(20, int(os.environ.get("DISCOVERY_ADD_TO_COUNT", "5"))))
_add_locks_guard = threading.Lock()
_add_locks: dict[int, threading.Lock] = {}


def _playlist_lock(playlist_id: int) -> threading.Lock:
    with _add_locks_guard:
        return _add_locks.setdefault(playlist_id, threading.Lock())


def _root_prompt(row) -> str:
    return refinement_context._root_prompt(row) or str(row["prompt"] or "").strip()


def _addition_prompt(row, live: list[dict], manual_removed: list[dict], *, refill: bool = False) -> str:
    specimens = [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in live[:20]
        if track.get("artist") and track.get("title")
    ]
    removed = as_exclusions(manual_removed)
    parts = [
        _root_prompt(row),
        "The current Spotify playlist is working. Add more music to it rather than rebuilding or changing direction.",
        "Treat the tracks still in the playlist as positive style specimens. Find new tracks that extend the same musical idea with useful variety while remaining faithful to the original source artist/song, genre, instrumentation, rhythmic feel, production language, and requested energy.",
    ]
    if row["description"]:
        parts.append(f"Current playlist description: {row['description']}")
    if specimens:
        parts.append("Current successful playlist tracks: " + "; ".join(specimens))
    if removed:
        parts.append("The user manually removed these tracks. Never add these exact tracks back during this addition: " + "; ".join(removed))
    parts.append(
        f"Return enough strong candidates to append {ADD_TO_COUNT} genuinely new tracks. Do not repeat anything already in the playlist. Favor artist variety except for an explicitly named inspiration artist, which may contribute a few strong tracks."
    )
    if refill:
        parts.append("Some first-pass candidates failed Spotify resolution. Find alternate tracks inside the same sound; do not broaden genre to fill the quota.")
    return "\n".join(part for part in parts if part)


def _resolve_new(token: str, requested: list[dict], live_uris: set[str], limit: int) -> tuple[list[dict], list[str]]:
    resolved: list[dict] = []
    missing: list[str] = []
    seen = set(live_uris)
    for item in requested:
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        if not artist or not title or artist_blocked(artist):
            continue
        track = tr.spotify.search_track(token, tr.spotify.TrackRequest(artist, title))
        if track and track.get("uri") and track["uri"] not in seen:
            resolved.append(track)
            seen.add(track["uri"])
            if len(resolved) >= limit:
                break
        elif not track:
            missing.append(f"{artist} - {title}")
    return resolved, missing


def _now():
    return datetime.now(timezone.utc).isoformat()


def _init_jobs():
    with tr.database() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS playlist_add_jobs (
            job_id TEXT PRIMARY KEY, playlist_id INTEGER NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL,
            count INTEGER NOT NULL, result TEXT, error TEXT, error_trace TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute("UPDATE playlist_add_jobs SET status='failed',stage='interrupted',"
                   "error='Server restarted. Check Spotify before retrying.',updated_at=? "
                   "WHERE status IN ('running','queued')", (_now(),))


def _payload(row):
    data = {key: row[key] for key in (
        "job_id", "playlist_id", "status", "stage", "progress",
        "error", "created_at", "updated_at",
    )}
    if row["result"]:
        data["result"] = json.loads(row["result"])
    return data


def _set_stage(job_id, stage, progress):
    with tr.database() as db:
        db.execute("UPDATE playlist_add_jobs SET stage=?,progress=?,updated_at=? WHERE job_id=?",
                   (stage, progress, _now(), job_id))
    print(f"[Tune Raider] Add to {job_id[:8]}: {stage} ({progress}%)", flush=True)


def _worker(job_id, playlist_id, count):
    with tr.app.app_context():
        try:
            with tr.database() as db:
                db.execute("UPDATE playlist_add_jobs SET status='running',updated_at=? WHERE job_id=?",
                           (_now(), job_id))
            result = _add_to_playlist_locked(
                playlist_id, count, stage_callback=lambda s, p: _set_stage(job_id, s, p),
            )
            with tr.database() as db:
                db.execute("UPDATE playlist_add_jobs SET status='complete',stage='complete',"
                           "progress=100,result=?,updated_at=? WHERE job_id=?",
                           (json.dumps(result), _now(), job_id))
        except Exception as exc:
            trace = traceback.format_exc()
            print(f"[Tune Raider] Add to {job_id} failed:\\n{trace}", flush=True)
            try:
                with tr.database() as db:
                    db.execute("UPDATE playlist_add_jobs SET status='failed',error=?,"
                               "error_trace=?,updated_at=? WHERE job_id=?",
                               (str(exc), trace[-8000:], _now(), job_id))
            except Exception:
                print(traceback.format_exc(), flush=True)


def add_to_playlist(playlist_id: int):
    body = request.get_json(silent=True) or {}
    count = body.get("count", ADD_TO_COUNT)
    count = max(1, min(20, count)) if type(count) is int else ADD_TO_COUNT
    job_id = str(body.get("request_id") or uuid.uuid4().hex)
    if len(job_id) > 128 or not job_id or not all(ch.isalnum() or ch in "._:-" for ch in job_id):
        return jsonify({"error": "Invalid Add to request ID."}), 400
    with tr.database() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM playlist_add_jobs WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            if existing["playlist_id"] != playlist_id:
                return jsonify({"error": "Request ID belongs to another playlist."}), 409
            return jsonify(_payload(existing)), 200 if existing["status"] in ("complete", "failed") else 202
        active = db.execute(
            "SELECT * FROM playlist_add_jobs WHERE playlist_id=? AND status IN ('queued','running') "
            "ORDER BY created_at DESC LIMIT 1", (playlist_id,),
        ).fetchone()
        if active:
            return jsonify(_payload(active)), 202
        playlist = db.execute("SELECT id FROM generated_playlists WHERE id=?", (playlist_id,)).fetchone()
        if not playlist:
            return jsonify({"error": "That playlist is no longer in local history."}), 404
        now = _now()
        db.execute("INSERT INTO playlist_add_jobs "
                   "(job_id,playlist_id,status,stage,progress,count,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,?,?)",
                   (job_id, playlist_id, "queued", "queued", 0, count, now, now))
    threading.Thread(target=_worker, args=(job_id, playlist_id, count),
                     name=f"tune-raider-add-{playlist_id}", daemon=True).start()
    return jsonify({"job_id": job_id, "playlist_id": playlist_id,
                    "status": "queued", "stage": "queued", "progress": 0}), 202


def add_to_status(job_id: str):
    with tr.database() as db:
        row = db.execute("SELECT * FROM playlist_add_jobs WHERE job_id=?", (job_id,)).fetchone()
    return jsonify(_payload(row)) if row else (jsonify({"status": "missing"}), 404)


def latest_add_to_status(playlist_id: int):
    with tr.database() as db:
        row = db.execute("SELECT * FROM playlist_add_jobs WHERE playlist_id=? "
                         "ORDER BY created_at DESC LIMIT 1", (playlist_id,)).fetchone()
    return jsonify(_payload(row) if row else {"status": "missing"})


def _add_to_playlist_locked(playlist_id: int, count: int, stage_callback=None):
    def stage(name, progress):
        if stage_callback:
            stage_callback(name, progress)
    stage("spotify_sync", 5)
    with tr.database() as connection:
        row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        return jsonify({"error": "That playlist is no longer in local history."}), 404

    ensure_playlist_read_scope(tr.spotify)
    token = tr.spotify.get_access_token()
    spotify_playlist_id, live = fetch_playlist_tracks(tr.spotify, token, row["spotify_url"])
    stored = json.loads(row["tracks"]) or json.loads(row["source_tracks"]) or []
    manual_removed, manual_added = compare_stored_to_live(tr.spotify, stored, live)

    if manual_removed or manual_added:
        record(
            tr.database,
            "spotify_manual_edit_observed",
            parent_playlist_id=row["id"],
            prompt=_root_prompt(row),
            payload={"removed_tracks": manual_removed, "added_tracks": manual_added, "observed_before": "add_to"},
        )

    excluded = as_exclusions(live + manual_removed)
    prompt = _addition_prompt(row, live, manual_removed)
    stage('discovery', 15)
    generated = tr.ask_for_hybrid_playlist(prompt, excluded)
    live_uris = {str(track.get("uri") or "") for track in live if track.get("uri")}
    stage('resolution', 55)
    resolved, missing = _resolve_new(token, list(generated.get("tracks") or []), live_uris, count)

    if len(resolved) < count:
        stage('refill', 65)
        refill_excluded = excluded + [
            f"{', '.join(a.get('name', '') for a in track.get('artists', []))} - {track.get('name', '')}"
            for track in resolved
        ]
        refill = tr.ask_for_hybrid_playlist(_addition_prompt(row, live, manual_removed, refill=True), refill_excluded)
        more, more_missing = _resolve_new(token, list(refill.get("tracks") or []), live_uris | {t["uri"] for t in resolved}, count - len(resolved))
        resolved.extend(more)
        missing.extend(more_missing)

    if not resolved:
        raise tr.AppError("No additional tracks could be resolved without repeating the current playlist.")

    # Discovery can take longer than the proxy timeout. Re-read Spotify just
    # before writing so a retry cannot append tracks written by the prior run.
    stage('duplicate_check', 82)
    _, latest_live = fetch_playlist_tracks(tr.spotify, token, row["spotify_url"])
    existing_uris = {track.get("uri") for track in latest_live if track.get("uri")}
    existing_keys = {normalized_key(tr.spotify, track) for track in latest_live}
    unique = []
    seen_uris = set(existing_uris)
    seen_keys = set(existing_keys)
    for track in resolved:
        uri = track.get("uri")
        record_key = normalized_key(tr.spotify, {
            "artist": ", ".join(a.get("name", "") for a in track.get("artists", [])),
            "title": track.get("name", ""),
        })
        if not uri or uri in seen_uris or record_key in seen_keys:
            continue
        seen_uris.add(uri)
        seen_keys.add(record_key)
        unique.append(track)
    resolved = unique
    if not resolved:
        return {
            "added": 0,
            "tracks": [],
            "playlist_id": row["id"],
            "notice": "All discovered tracks are already in Spotify. No duplicates were added.",
        }
    stage('spotify_write', 90)
    tr.spotify.add_items(token, spotify_playlist_id, [track["uri"] for track in resolved])
    added = [
        {
            "artist": ", ".join(artist.get("name", "") for artist in track.get("artists", [])),
            "title": track.get("name", ""),
            "url": (track.get("external_urls") or {}).get("spotify"),
            "uri": track.get("uri"),
        }
        for track in resolved
    ]
    updated = latest_live + added
    stored_tracks = [
        {"artist": track.get("artist", ""), "title": track.get("title", ""), "url": track.get("url")}
        for track in updated
    ]
    source_tracks = [
        {"artist": track.get("artist", ""), "title": track.get("title", ""), "source": "spotify-live" if index < len(latest_live) else "spotify-add-to"}
        for index, track in enumerate(updated)
    ]
    stage('history_save', 96)
    with tr.database() as connection:
        connection.execute(
            "UPDATE generated_playlists SET tracks = ?, source_tracks = ? WHERE id = ?",
            (json.dumps(stored_tracks), json.dumps(source_tracks), row["id"]),
        )

    record(
        tr.database,
        "add_to",
        playlist_id=row["id"],
        parent_playlist_id=row["id"],
        prompt=_root_prompt(row),
        payload={
            "requested_count": count,
            "added_tracks": added,
            "manual_removed_tracks": manual_removed,
            "manual_added_tracks": manual_added,
            "interpretation": "current_playlist_positive_specimen",
        },
    )
    print(
        f"[Tune Raider] add to: {len(latest_live)} live + {len(added)} new; {len(manual_removed)} manual removals excluded",
        flush=True,
    )
    return {
        "added": len(added),
        "tracks": added,
        "playlist_id": row["id"],
        "spotify_url": row["spotify_url"],
        "missing": missing,
        "notice": "" if len(added) >= count else f"Added {len(added)} of {count} requested tracks without loosening the playlist's sound.",
    }


_init_jobs()
tr.app.add_url_rule("/api/add-to-status/<job_id>", endpoint="add_to_status", view_func=add_to_status, methods=["GET"])
tr.app.add_url_rule("/api/history/<int:playlist_id>/add-status", endpoint="latest_add_to_status", view_func=latest_add_to_status, methods=["GET"])
tr.app.add_url_rule("/api/history/<int:playlist_id>/add", endpoint="add_to_playlist", view_func=add_to_playlist, methods=["POST"])
