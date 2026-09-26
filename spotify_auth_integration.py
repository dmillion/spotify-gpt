"""Flask integration for proactive Spotify authorization checks."""
from __future__ import annotations

import requests
from flask import jsonify, request

import app as tone_raider
import spotify_playlist as spotify
from spotify_auth import SpotifyAuthorizationRequired, auth_status, install_auth_retry, require_authorized

install_auth_retry()

_PROTECTED_MUTATION_PATHS = (
    "/api/generate",
    "/api/history/",
)


@tone_raider.app.before_request
def require_spotify_before_music_work():
    """Fail before Ollama work if Spotify authorization cannot be recovered."""
    path = request.path
    if request.method != "POST":
        return None
    if path == "/api/generate" or (path.startswith("/api/history/") and (path.endswith("/regenerate") or path.endswith("/refine"))):
        try:
            require_authorized()
        except SpotifyAuthorizationRequired as exc:
            return jsonify({
                "error": str(exc),
                "spotify_reauthorize": True,
            }), 401
        except (spotify.SpotifyError, requests.RequestException) as exc:
            return jsonify({
                "error": str(exc),
                "spotify_reauthorize": False,
            }), 502
    return None


@tone_raider.app.get("/api/spotify-auth/status")
def spotify_auth_status():
    status = auth_status(verify=True)
    return jsonify(status), (200 if status.get("authorized") else 401 if status.get("reauthorize") else 503)


@tone_raider.app.post("/api/spotify-auth/connect")
def spotify_auth_connect():
    """Run the existing local PKCE authorization flow after explicit user action."""
    try:
        token = spotify.get_access_token()
        if not token:
            raise SpotifyAuthorizationRequired("Spotify authorization did not complete.")
        status = auth_status(verify=True)
        if not status.get("authorized"):
            raise SpotifyAuthorizationRequired(str(status.get("reason") or "Spotify authorization did not complete."))
        return jsonify({"authorized": True})
    except (SpotifyAuthorizationRequired, spotify.SpotifyError, requests.RequestException) as exc:
        return jsonify({"authorized": False, "error": str(exc), "spotify_reauthorize": True}), 401


@tone_raider.app.after_request
def inject_spotify_auth_client(response):
    """Load the auth UI without modifying the legacy template directly."""
    content_type = response.headers.get("Content-Type", "")
    if response.status_code == 200 and "text/html" in content_type:
        try:
            html = response.get_data(as_text=True)
        except UnicodeDecodeError:
            return response
        if "spotify_auth.js" not in html and "</head>" in html:
            html = html.replace(
                "</head>",
                '<script defer src="/static/spotify_auth.js"></script>\n</head>',
                1,
            )
            response.set_data(html)
            response.headers["Content-Length"] = str(len(response.get_data()))
    return response
