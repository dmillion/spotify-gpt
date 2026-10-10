"""Playlist creation/history routes installed into app.py."""
from __future__ import annotations

import json
import os
import queue
import re
import threading
from datetime import datetime, timezone
import requests
from flask import jsonify, render_template, request


def install(ns: dict) -> None:
    app = ns["app"]
    spotify = ns["spotify"]
    AppError = ns["AppError"]
    generation_worker_lock = threading.Lock()
    generation_queue = queue.Queue()
    generation_queue_limit = max(1, int(os.environ.get("GENERATION_QUEUE_LIMIT", "3")))
    generation_worker_started = False

    class GenerationCancelled(Exception):
        pass

    def _stage_error(stage: str, prefix: str, exc: Exception, *, spotify_created=False, spotify_written=False, spotify_url=None):
        message = str(exc).strip() or exc.__class__.__name__
        error = AppError(
            f"{prefix}: {message}",
            getattr(exc, "status_code", 502),
            getattr(exc, "help_url", None),
        )
        error.stage = stage
        error.spotify_created = bool(spotify_created)
        error.spotify_written = bool(spotify_written)
        error.spotify_url = spotify_url
        raise error from exc

    def create_from_prompt(prompt: str, excluded_tracks: list[str] | None = None, stage_callback=None) -> dict:
        def stage(name: str) -> None:
            if stage_callback:
                stage_callback(name)

        ns["require_configuration"]()
        stage("curation")
        try:
            generated = ns["ask_for_hybrid_playlist"](prompt, excluded_tracks)
        except Exception as exc:
            _stage_error("curation", "Playlist curation failed", exc)

        stage("spotify_auth")
        try:
            token = spotify.get_access_token()
        except Exception as exc:
            _stage_error("spotify_auth", "Spotify authorization failed", exc)

        stage("spotify_resolution")
        resolved = []
        missing = []
        seen_uris = set()
        try:
            for requested in generated["tracks"]:
                req = spotify.TrackRequest(requested["artist"], requested["title"])
                track = spotify.search_track(token, req)
                if track and track.get("uri") not in seen_uris:
                    resolved.append(track)
                    seen_uris.add(track["uri"])
                elif not track:
                    missing.append(f"{requested['artist']} - {requested['title']}")
        except Exception as exc:
            _stage_error("spotify_resolution", "Spotify track resolution failed", exc)

        if not resolved:
            error = AppError("Spotify could not resolve any tracks from the generated playlist.")
            error.stage = "spotify_resolution"
            error.spotify_created = False
            error.spotify_written = False
            error.spotify_url = None
            raise error

        description = str(generated.get("description") or spotify.DEFAULT_DESCRIPTION).strip()
        name = str(generated.get("name") or "New Playlist").strip()
        playlist = None
        spotify_url = None
        stage("spotify_create")
        try:
            playlist = spotify.create_playlist(token, name=name, description=description, public=False)
            spotify_url = playlist.get("external_urls", {}).get("spotify")
        except Exception as exc:
            _stage_error("spotify_create", "Spotify playlist creation failed", exc)

        stage("spotify_write")
        try:
            spotify.add_items(token, playlist["id"], [track["uri"] for track in resolved])
        except Exception as exc:
            _stage_error(
                "spotify_write",
                "Spotify created the playlist, but adding tracks failed",
                exc,
                spotify_created=True,
                spotify_written=False,
                spotify_url=spotify_url,
            )

        tracks = [
            {
                "artist": ", ".join(a["name"] for a in track.get("artists", [])),
                "title": track["name"],
                "url": track.get("external_urls", {}).get("spotify"),
            }
            for track in resolved
        ]
        result = {
            "prompt": prompt,
            "name": playlist.get("name", generated.get("name", "New Playlist")),
            "description": description,
            "tracks": tracks,
            "spotify_url": spotify_url,
            "missing": missing,
            "source": "hybrid",
            "source_tracks": generated["tracks"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "spotify_written": True,
        }
        stage("history_save")
        try:
            with ns["database"]() as connection:
                cursor = connection.execute(
                    "INSERT INTO generated_playlists (prompt, name, description, tracks, spotify_url, created_at, source, source_tracks) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result["prompt"], result["name"], result["description"], json.dumps(tracks),
                        result["spotify_url"], result["created_at"], result["source"], json.dumps(generated["tracks"]),
                    ),
                )
                result["id"] = cursor.lastrowid
        except Exception as exc:
            _stage_error(
                "history_save",
                "Spotify playlist was written, but Tune Raider could not save local history",
                exc,
                spotify_created=True,
                spotify_written=True,
                spotify_url=spotify_url,
            )
        return result

    def _generation_request_id(value) -> str:
        request_id = str(value or "").strip()
        if not request_id:
            return ""
        if len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
            raise AppError("Invalid generation request ID.", 400)
        return request_id

    def _generation_job_payload(row) -> dict:
        if not row:
            return {"status": "missing"}
        payload = {
            "cancel_requested": bool(row["cancel_requested"]),
            "request_id": row["request_id"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": int(row["progress"] or 0),
            "error": row["error"],
            "spotify_created": bool(row["spotify_created"]),
            "spotify_written": bool(row["spotify_written"]),
            "spotify_url": row["spotify_url"],
        }
        if row["status"] == "queued":
            with ns["database"]() as connection:
                ahead = connection.execute(
                    "SELECT COUNT(*) FROM generation_requests WHERE status='queued' AND created_at < ?",
                    (row["created_at"],),
                ).fetchone()[0]
            payload["queue_position"] = int(ahead) + 1
            payload["queue_limit"] = generation_queue_limit
        if row["result"]:
            try:
                payload["result"] = json.loads(row["result"])
            except (TypeError, ValueError):
                payload["result"] = None
        payload["retryable"] = row["status"] == "failed" and row["stage"] != "interrupted" and not bool(row["spotify_created"])
        return payload

    def _generation_job(request_id: str):
        with ns["database"]() as connection:
            return connection.execute(
                "SELECT * FROM generation_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()

    def _begin_generation_job(request_id: str, prompt: str, retry: bool) -> tuple[str, dict | None]:
        now = datetime.now(timezone.utc).isoformat()
        with ns["database"]() as connection:
            row = connection.execute(
                "SELECT * FROM generation_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row:
                state = _generation_job_payload(row)
                if row["status"] == "complete":
                    return "complete", state.get("result")
                if row["status"] == "running":
                    return "running", None
                if row["status"] == "queued":
                    return "queued", None
                if row["status"] == "failed":
                    if not retry:
                        return "failed", state
                    if not state["retryable"]:
                        return "failed", state
                    queued_count = connection.execute("SELECT COUNT(*) FROM generation_requests WHERE status='queued'").fetchone()[0]
                    running_count = connection.execute("SELECT COUNT(*) FROM generation_requests WHERE status='running'").fetchone()[0]
                    if running_count + queued_count >= generation_queue_limit + 1:
                        return "full", None
                    connection.execute(
                        "UPDATE generation_requests SET status='queued',stage='queued',progress=0,error=NULL,result=NULL,spotify_created=0,spotify_written=0,spotify_url=NULL,updated_at=? WHERE request_id=?",
                        (now, request_id),
                    )
                    return "start", None
            queued_count = connection.execute("SELECT COUNT(*) FROM generation_requests WHERE status='queued'").fetchone()[0]
            running_count = connection.execute("SELECT COUNT(*) FROM generation_requests WHERE status='running'").fetchone()[0]
            if running_count + queued_count >= generation_queue_limit + 1:
                return "full", None
            connection.execute(
                "INSERT INTO generation_requests (request_id,prompt,status,stage,progress,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (request_id, prompt, "queued", "queued", 0, now, now),
            )
        return "start", None

    def _finish_generation_job(request_id: str, result: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with ns["database"]() as connection:
            connection.execute(
                "UPDATE generation_requests SET status='complete',stage='complete',progress=100,error=NULL,result=?,spotify_created=1,spotify_written=1,spotify_url=?,updated_at=? WHERE request_id=?",
                (json.dumps(result), result.get("spotify_url"), now, request_id),
            )

    def _fail_generation_job(request_id: str, exc: Exception) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with ns["database"]() as connection:
            connection.execute(
                "UPDATE generation_requests SET status='failed',stage=?,error=?,spotify_created=?,spotify_written=?,spotify_url=?,updated_at=? WHERE request_id=?",
                (
                    str(getattr(exc, "stage", "unknown")),
                    str(exc),
                    1 if getattr(exc, "spotify_created", False) else 0,
                    1 if getattr(exc, "spotify_written", False) else 0,
                    getattr(exc, "spotify_url", None),
                    now,
                    request_id,
                ),
            )


    GENERATION_PROGRESS = {
        "curation": 8,
        "spotify_auth": 58,
        "spotify_resolution": 68,
        "spotify_create": 86,
        "spotify_write": 92,
        "history_save": 97,
        "complete": 100,
    }

    def _update_generation_stage(request_id: str, stage: str) -> None:
        with ns["database"]() as db:
            current = db.execute("SELECT cancel_requested FROM generation_requests WHERE request_id=?", (request_id,)).fetchone()
        if current and current["cancel_requested"]:
            raise GenerationCancelled("Playlist generation canceled before the next stage.")
        now = datetime.now(timezone.utc).isoformat()
        progress = GENERATION_PROGRESS.get(stage, 5)
        with ns["database"]() as connection:
            connection.execute(
                "UPDATE generation_requests SET stage=?,progress=?,updated_at=? WHERE request_id=? AND status='running'",
                (stage, progress, now, request_id),
            )
        print(f"[Tune Raider] generation {request_id[:12]}: {stage} ({progress}%)", flush=True)

    def _run_generation_job(request_id: str, prompt: str) -> None:
        """Run exactly one queued generation at a time."""
        now = datetime.now(timezone.utc).isoformat()
        with ns["database"]() as connection:
            connection.execute(
                "UPDATE generation_requests SET status='running',stage='curation',progress=5,updated_at=? WHERE request_id=?",
                (now, request_id),
            )
        print(f"[Tune Raider] starting queued generation {request_id[:12]}", flush=True)
        try:
            with ns["database"]() as db:
                current = db.execute("SELECT cancel_requested FROM generation_requests WHERE request_id=?", (request_id,)).fetchone()
            if current and current["cancel_requested"]:
                raise GenerationCancelled("Canceled while queued.")
            result = create_from_prompt(
                prompt,
                stage_callback=lambda stage: _update_generation_stage(request_id, stage),
            )
            _finish_generation_job(request_id, result)
        except GenerationCancelled as exc:
            with ns["database"]() as db:
                db.execute("UPDATE generation_requests SET status='canceled',stage='canceled',error=?,updated_at=? WHERE request_id=?",
                           (str(exc), datetime.now(timezone.utc).isoformat(), request_id))
        except Exception as exc:
            try:
                _fail_generation_job(request_id, exc)
            except Exception as persist_exc:
                print(
                    f"[Tune Raider] queued generation {request_id} failed and status persistence also failed: {persist_exc}",
                    flush=True,
                )
            print(f"[Tune Raider] queued generation {request_id} failed: {exc}", flush=True)

    def _generation_queue_worker() -> None:
        while True:
            request_id, prompt = generation_queue.get()
            try:
                with ns["database"]() as db:
                    state = db.execute("SELECT status FROM generation_requests WHERE request_id=?", (request_id,)).fetchone()
                if state and state["status"] == "queued":
                    _run_generation_job(request_id, prompt)
            except Exception as exc:
                print(f"[Tune Raider] generation worker error for {request_id[:12]}: {exc}", flush=True)
            finally:
                generation_queue.task_done()
                if generation_queue.empty():
                    unload = ns.get("unload_ollama_model")
                    if callable(unload):
                        try:
                            unload()
                        except Exception as exc:
                            print(f"[Tune Raider] model unload error: {exc}", flush=True)

    def _ensure_generation_worker() -> None:
        nonlocal generation_worker_started
        with generation_worker_lock:
            if generation_worker_started:
                return
            # Recover only once per server process, not on each database connection.
            # An interrupted Spotify write has an uncertain outcome: never replay it
            # automatically and risk creating a duplicate playlist.
            with ns["database"]() as connection:
                connection.execute(
                    "UPDATE generation_requests SET status='failed',stage='interrupted',"
                    "error='Tune Raider restarted while this job was running. Check Spotify before resubmitting; a playlist may already exist.',"
                    "updated_at=? WHERE status='running'",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                pending = connection.execute(
                    "SELECT request_id,prompt FROM generation_requests WHERE status='queued' "
                    "ORDER BY created_at, rowid"
                ).fetchall()
            for row in pending:
                generation_queue.put((row["request_id"], row["prompt"]))
            worker = threading.Thread(
                target=_generation_queue_worker,
                name="tune-raider-generation-worker",
                daemon=True,
            )
            worker.start()
            generation_worker_started = True
            if pending:
                print(f"[Tune Raider] recovered {len(pending)} waiting playlist job(s)", flush=True)

    def _launch_generation_job(request_id: str, prompt: str) -> None:
        generation_queue.put((request_id, prompt))
        print(
            f"[Tune Raider] queued generation {request_id[:12]} "
            f"(pending in memory: {generation_queue.qsize()})",
            flush=True,
        )

    def row_to_result(row) -> dict:
        return {"id": row["id"], "source": row["source"], "source_tracks": json.loads(row["source_tracks"]), "prompt": row["prompt"],
                "name": row["name"], "description": row["description"], "tracks": json.loads(row["tracks"]),
                "spotify_url": row["spotify_url"], "created_at": row["created_at"]}

    def _spotify_playlist_id(value: str | None) -> str:
        text = str(value or "").strip()
        marker = "/playlist/"
        if marker not in text:
            return ""
        playlist_id = text.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].split("/", 1)[0].strip()
        return playlist_id if playlist_id and playlist_id.isalnum() else ""

    def _current_spotify_playlist_ids() -> set[str] | None:
        """Silently return playlists visible to the cached Spotify account.

        History loading must never launch OAuth. If the cached token is absent,
        stale, or missing the private-playlist scope, leave local history alone.
        """
        token_info = spotify.load_token()
        if not token_info:
            print("[Tune Raider] history sync skipped: no cached Spotify token", flush=True)
            return None
        if not spotify.token_has_required_scopes(token_info):
            granted = set(str(token_info.get("scope", "")).split())
            missing = sorted(spotify.required_scopes() - granted)
            print(
                "[Tune Raider] Spotify authorization needs updated scope(s): "
                + ", ".join(missing),
                flush=True,
            )
            # This is a one-time scope migration for existing installs. Refresh
            # tokens cannot gain scopes, so use the normal PKCE authorization
            # flow and resume this history request after it completes.
            try:
                token = spotify.get_access_token()
            except (requests.RequestException, spotify.SpotifyError):
                print("[Tune Raider] history sync skipped: Spotify reauthorization did not complete", flush=True)
                return None
        else:
            token = str(token_info.get("access_token") or "").strip()
        if not token:
            return None

        ids: set[str] = set()
        offset = 0
        try:
            while True:
                payload = spotify.api_request(
                    "GET",
                    "/me/playlists",
                    token,
                    params={"limit": 50, "offset": offset},
                ).json()
                items = payload.get("items") or []
                for item in items:
                    playlist_id = str((item or {}).get("id") or "").strip()
                    if playlist_id:
                        ids.add(playlist_id)
                offset += len(items)
                if not items or offset >= int(payload.get("total") or 0):
                    break
        except (requests.RequestException, spotify.SpotifyError):
            return None
        return ids

    def _trim_deleted_spotify_history() -> int:
        current_ids = _current_spotify_playlist_ids()
        if current_ids is None:
            return 0

        with ns["database"]() as connection:
            rows = connection.execute(
                "SELECT id, spotify_url FROM generated_playlists WHERE spotify_url IS NOT NULL AND spotify_url != ''"
            ).fetchall()
            stale_ids = [
                int(row["id"])
                for row in rows
                if _spotify_playlist_id(row["spotify_url"])
                and _spotify_playlist_id(row["spotify_url"]) not in current_ids
            ]
            if stale_ids:
                placeholders = ",".join("?" for _ in stale_ids)
                connection.execute(
                    f"DELETE FROM generated_playlists WHERE id IN ({placeholders})",
                    stale_ids,
                )

        print(
            f"[Tune Raider] history sync: checked {len(rows)} local build(s), "
            f"found {len(current_ids)} Spotify playlist(s), removed {len(stale_ids)} stale build(s)",
            flush=True,
        )
        return len(stale_ids)

    @app.get("/")
    def home():
        return render_template("index.html", password_gate_enabled=bool(ns["APP_PASSWORD"]))

    @app.get("/api/library")
    def library_status():
        try:
            library = ns["Library"](ns["AUDIO_DATABASE"])
            return jsonify({"available": True, "tracks": len(library.rows), "axes": list(library.summary()["axes"])})
        except Exception as exc:
            return jsonify({"available": False, "error": str(exc)})

    @app.get("/api/history")
    def history():
        _trim_deleted_spotify_history()
        with ns["database"]() as connection:
            rows = connection.execute("SELECT * FROM generated_playlists ORDER BY id DESC LIMIT 30").fetchall()
        return jsonify([row_to_result(row) for row in rows])

    @app.get("/api/usage")
    def token_usage():
        today = datetime.now(timezone.utc).date().isoformat()
        with ns["database"]() as connection:
            totals = dict(connection.execute(
                "SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens),0) AS input_tokens, COALESCE(SUM(output_tokens),0) AS output_tokens, COALESCE(SUM(total_tokens),0) AS total_tokens, COALESCE(SUM(CASE WHEN created_at >= ? THEN total_tokens ELSE 0 END),0) AS today_tokens, COUNT(*)-COUNT(total_tokens) AS unreported_requests, MIN(created_at) AS first_recorded_at FROM model_usage WHERE provider='ollama'",
                (today,),
            ).fetchone())
            latest = connection.execute("SELECT * FROM model_usage WHERE provider='ollama' ORDER BY id DESC LIMIT 1").fetchone()
        return jsonify(**totals, provider="ollama", configured_model=ns["OLLAMA_MODEL"], latest=dict(latest) if latest else None)

    @app.get("/api/generation-status/<request_id>")
    def generation_status(request_id: str):
        _ensure_generation_worker()
        try:
            request_id = _generation_request_id(request_id)
        except AppError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        row = _generation_job(request_id)
        if not row:
            return jsonify({"status": "missing", "request_id": request_id}), 404
        return jsonify(_generation_job_payload(row))

    @app.get("/api/generation-overview")
    def generation_overview():
        """One-shot snapshot for any browser, including clients that did not submit the job."""
        _ensure_generation_worker()
        with ns["database"]() as connection:
            active = connection.execute(
                "SELECT * FROM generation_requests WHERE status='running' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            waiting = connection.execute(
                "SELECT COUNT(*) FROM generation_requests WHERE status='queued'"
            ).fetchone()[0]
        return jsonify({
            "active": {
                "request_id": active["request_id"],
                "stage": active["stage"],
                "progress": int(active["progress"] or 0),
                "started_at": active["updated_at"],
            } if active else None,
            "waiting": int(waiting),
            "queue_limit": generation_queue_limit,
        })

    @app.post("/api/generation-cancel/<request_id>")
    def generation_cancel(request_id: str):
        try:
            request_id = _generation_request_id(request_id)
        except AppError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        with ns["database"]() as db:
            row = db.execute("SELECT * FROM generation_requests WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                return jsonify({"error": "Generation job not found."}), 404
            if row["status"] == "queued":
                db.execute("UPDATE generation_requests SET status='canceled',stage='canceled',cancel_requested=1,"
                           "error='Canceled before starting.',updated_at=? WHERE request_id=?",
                           (datetime.now(timezone.utc).isoformat(), request_id))
            elif row["status"] == "running":
                db.execute("UPDATE generation_requests SET cancel_requested=1,updated_at=? WHERE request_id=?",
                           (datetime.now(timezone.utc).isoformat(), request_id))
        return jsonify(_generation_job_payload(_generation_job(request_id)))

    @app.post("/api/generate")
    def generate():
        body = request.get_json(silent=True) or {}
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            return jsonify({"error": "Tell me what kind of playlist you want first."}), 400

        try:
            request_id = _generation_request_id(body.get("request_id"))
        except AppError as exc:
            return jsonify({"error": str(exc)}), exc.status_code

        # Every request, including older clients, must respect the worker queue.
        if not request_id:
            request_id = __import__("uuid").uuid4().hex

        _ensure_generation_worker()
        with generation_worker_lock:
            state, existing = _begin_generation_job(request_id, prompt, bool(body.get("retry")))
            if state == "start":
                _launch_generation_job(request_id, prompt)
        if state == "complete":
            return jsonify(existing)
        if state in {"running", "queued"}:
            current_job = _generation_job(request_id)
            return jsonify(_generation_job_payload(current_job)), 202
        if state == "full":
            return jsonify({
                "error": f"Tune Raider is busy. The queue is limited to {generation_queue_limit} waiting playlist builds.",
                "status": "queue_full",
                "queue_limit": generation_queue_limit,
                "retryable": True,
            }), 429
        if state == "failed":
            return jsonify(existing), 409

        return jsonify({
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "queue_limit": generation_queue_limit,
            "request_id": request_id,
            "message": "Playlist generation is queued on the Tune Raider server. You can leave this page.",
        }), 202

    @app.post("/api/history/<int:playlist_id>/regenerate")
    def regenerate(playlist_id: int):
        with ns["database"]() as connection:
            row = connection.execute("SELECT * FROM generated_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not row: return jsonify({"error": "That playlist is no longer in local history."}), 404
        old = [f"{t['artist']} - {t['title']}" for t in (json.loads(row["source_tracks"]) or json.loads(row["tracks"]))]
        try: return jsonify(create_from_prompt(row["prompt"], old))
        except (AppError, requests.RequestException, spotify.SpotifyError) as exc:
            return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)

    ns.update({"create_from_prompt": create_from_prompt, "row_to_result": row_to_result, "home": home,
               "library_status": library_status, "history": history, "token_usage": token_usage,
               "generate": generate, "generation_status": generation_status,
               "generation_overview": generation_overview, "generation_cancel": generation_cancel, "regenerate": regenerate})
