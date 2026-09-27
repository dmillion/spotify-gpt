#!/usr/bin/env python3
"""Local prompt-to-Spotify-playlist app."""

from __future__ import annotations

import hmac
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import lastfm_client as lastfm
import spotify_playlist as spotify
from audio.library_context import Library

load_dotenv()


def ollama_think_setting():
    raw = os.environ.get("OLLAMA_THINK", "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"low", "medium", "high"}:
        return raw
    return False


ROOT = Path(__file__).parent
DATABASE = Path(os.environ.get("PLAYLIST_HISTORY_DB", ROOT / "data" / "playlist_history.db"))
AUDIO_DATABASE = Path(os.environ.get("AUDIO_LIBRARY_DB", ROOT / "data" / "audio_library.sqlite"))
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "https://ollama.com/api/chat").strip()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b").strip()
OLLAMA_TIMEOUT = max(1, int(os.environ.get("OLLAMA_TIMEOUT", "300")))
OLLAMA_THINK = ollama_think_setting()
OLLAMA_LOCAL_CANDIDATE_LIMIT = max(20, int(os.environ.get("OLLAMA_LOCAL_CANDIDATE_LIMIT", "60")))
OLLAMA_EXTERNAL_CANDIDATE_LIMIT = max(0, int(os.environ.get("OLLAMA_EXTERNAL_CANDIDATE_LIMIT", "20")))
PLAYLIST_TRACK_LIMIT = max(1, int(os.environ.get("PLAYLIST_TRACK_LIMIT", "20")))
PLAYLIST_ARTIST_LIMIT = max(1, int(os.environ.get("PLAYLIST_ARTIST_LIMIT", "2")))
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
APP_SESSION_SECRET = os.environ.get("APP_SESSION_SECRET", "").strip()

RETRIEVAL_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "artists": {"type": "array", "items": {"type": "string"}},
        "terms": {"type": "array", "items": {"type": "string"}},
        "sound": {
            "type": "object",
            "additionalProperties": {"type": "number", "minimum": 0, "maximum": 100},
        },
    },
    "required": ["artists", "terms", "sound"],
    "additionalProperties": False,
}

PLAYLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"candidate_id": {"type": "string"}},
                "required": ["candidate_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "description", "tracks"],
    "additionalProperties": False,
}

app = Flask(__name__)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("APP_SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"},
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

if APP_PASSWORD:
    if not APP_SESSION_SECRET:
        raise RuntimeError("APP_SESSION_SECRET must be set when APP_PASSWORD is enabled.")
    app.secret_key = APP_SESSION_SECRET


class AppError(RuntimeError):
    def __init__(self, message, status_code=502, help_url=None):
        super().__init__(message)
        self.status_code = status_code
        self.help_url = help_url


def check_ollama_response(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("error") or payload.get("message") or "").strip()
    detail = f" {message}" if message else ""
    settings_url = "https://ollama.com/settings"
    pricing_url = "https://ollama.com/pricing"
    if response.status_code == 401:
        raise AppError("Ollama rejected the API key. Check OLLAMA_API_KEY and try again.", 401, settings_url)
    if response.status_code == 403:
        raise AppError(
            f"This Ollama account cannot use the selected model ({OLLAMA_MODEL}). Choose a starter model available to your account or add usage credits.{detail}",
            403,
            pricing_url,
        )
    if response.status_code == 404:
        raise AppError(
            f"Ollama could not find model '{OLLAMA_MODEL}'. Set OLLAMA_MODEL to a model available to your account.{detail}",
            404,
            "https://ollama.com/search",
        )
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "").strip()
        wait = f" Retry after about {retry_after} seconds." if retry_after.isdigit() else ""
        raise AppError(
            f"Ollama's free-tier usage, concurrency, or rate limit was reached.{wait}{detail}",
            429,
            pricing_url,
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise AppError(f"Ollama request failed with HTTP {response.status_code}.{detail}") from exc


def database() -> sqlite3.Connection:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            tracks TEXT NOT NULL,
            spotify_url TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(generated_playlists)")}
    if "source" not in columns:
        connection.execute("ALTER TABLE generated_playlists ADD COLUMN source TEXT NOT NULL DEFAULT 'discovery'")
    if "source_tracks" not in columns:
        connection.execute("ALTER TABLE generated_playlists ADD COLUMN source_tracks TEXT NOT NULL DEFAULT '[]'")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            playlist_id INTEGER,
            parent_playlist_id INTEGER,
            prompt TEXT,
            instruction TEXT,
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_learning_events_type_created ON learning_events(event_type, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_learning_events_parent ON learning_events(parent_playlist_id)"
    )
    connection.commit()
    return connection


def require_configuration() -> None:
    missing = []
    if not os.environ.get("OLLAMA_API_KEY", "").strip():
        missing.append("OLLAMA_API_KEY")
    if not OLLAMA_MODEL:
        missing.append("OLLAMA_MODEL")
    if not spotify.CLIENT_ID:
        missing.append("SPOTIFY_CLIENT_ID")
    if missing:
        raise AppError(f"Add {', '.join(missing)} to .env before generating a playlist.")


def safe_next_url(value: str | None) -> str:
    if not value:
        return url_for("home")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return url_for("home")
    return value


@app.before_request
def require_login():
    if not APP_PASSWORD:
        return None
    if request.endpoint in {"login", "static"}:
        return None
    if session.get("authenticated") is True:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required."}), 401
    return redirect(url_for("login", next=request.full_path if request.query_string else request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("home"))
    if session.get("authenticated") is True:
        return redirect(safe_next_url(request.args.get("next")))
    error = None
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if hmac.compare_digest(supplied, APP_PASSWORD):
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            return redirect(safe_next_url(request.form.get("next")))
        error = "Incorrect password."
    return render_template("login.html", error=error, next_url=safe_next_url(request.args.get("next")))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# Remaining application implementation unchanged below this point.
