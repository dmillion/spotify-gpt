"""Playlist creation/history routes installed into app.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
import requests
from flask import jsonify, render_template, request


def install(ns: dict) -> None:
    app = ns["app"]
    spotify = ns["spotify"]
    AppError = ns["AppError"]

    def create_from_prompt(prompt: str, excluded_tracks: list[str] | None = None) -> dict:
        ns["require_configuration"]()
        generated = ns["ask_for_hybrid_playlist"](prompt, excluded_tracks)
        token = spotify.get_access_token()
        resolved = []; missing = []; seen_uris = set()
        for requested in generated["tracks"]:
            req = spotify.TrackRequest(requested["artist"], requested["title"])
            track = spotify.search_track(token, req)
            if track and track.get("uri") not in seen_uris:
                resolved.append(track); seen_uris.add(track["uri"])
            elif not track:
                missing.append(f"{requested['artist']} - {requested['title']}")
        if not resolved:
            raise AppError("Spotify could not resolve any tracks from the generated playlist.")
        description = str(generated.get("description") or spotify.DEFAULT_DESCRIPTION).strip()
        playlist = spotify.create_playlist(token, name=str(generated.get("name") or "New Playlist").strip(), description=description, public=False)
        spotify.add_items(token, playlist["id"], [track["uri"] for track in resolved])
        tracks = [{"artist": ", ".join(a["name"] for a in track.get("artists", [])), "title": track["name"], "url": track.get("external_urls", {}).get("spotify")} for track in resolved]
        result = {"prompt": prompt, "name": playlist.get("name", generated.get("name", "New Playlist")), "description": description,
                  "tracks": tracks, "spotify_url": playlist.get("external_urls", {}).get("spotify"), "missing": missing,
                  "source": "hybrid", "source_tracks": generated["tracks"], "created_at": datetime.now(timezone.utc).isoformat()}
        with ns["database"]() as connection:
            cursor = connection.execute(
                "INSERT INTO generated_playlists (prompt, name, description, tracks, spotify_url, created_at, source, source_tracks) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (result["prompt"], result["name"], result["description"], json.dumps(tracks), result["spotify_url"], result["created_at"], result["source"], json.dumps(generated["tracks"])),
            )
            result["id"] = cursor.lastrowid
        return result

    def row_to_result(row) -> dict:
        return {"id": row["id"], "source": row["source"], "source_tracks": json.loads(row["source_tracks"]), "prompt": row["prompt"],
                "name": row["name"], "description": row["description"], "tracks": json.loads(row["tracks"]),
                "spotify_url": row["spotify_url"], "created_at": row["created_at"]}

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

    @app.post("/api/generate")
    def generate():
        body = request.get_json(silent=True) or {}
        prompt = str(body.get("prompt", "")).strip()
        if not prompt: return jsonify({"error": "Tell me what kind of playlist you want first."}), 400
        try: return jsonify(create_from_prompt(prompt))
        except (AppError, requests.RequestException, spotify.SpotifyError) as exc:
            return jsonify({"error": str(exc), "help_url": getattr(exc, "help_url", None)}), getattr(exc, "status_code", 502)

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
               "generate": generate, "regenerate": regenerate})
