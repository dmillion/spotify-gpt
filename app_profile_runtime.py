"""Prompt-profile endpoint installed into app.py."""
from __future__ import annotations
import random
import requests
from flask import jsonify


def install(ns: dict) -> None:
    app = ns["app"]
    spotify = ns["spotify"]
    lastfm = ns["lastfm"]

    @app.get("/api/prompt-profile")
    def prompt_profile():
        if not spotify.CLIENT_ID:
            return jsonify({"artists": [], "genres": [], "profiles": [], "error": "Spotify is not configured."}), 503
        token_info = spotify.load_token()
        if not token_info or not spotify.token_has_required_scopes(token_info):
            return jsonify({"artists": [], "genres": [], "profiles": [], "reauthorize": True,
                            "error": "Spotify authorization needs the Liked Songs permission."}), 409
        token = str(token_info.get("access_token") or "").strip()
        if not token:
            return jsonify({"artists": [], "genres": [], "profiles": [], "reauthorize": True,
                            "error": "Spotify authorization needs to be refreshed."}), 409
        local_genres = {}
        try:
            library = ns["Library"](ns["AUDIO_DATABASE"])
            for row in library.rows:
                artist = str(row.get("artist") or "").strip(); genre = str(row.get("genre") or "").strip().lower()
                if not artist or not genre: continue
                bucket = local_genres.setdefault(artist.casefold(), [])
                if genre not in bucket: bucket.append(genre)
        except Exception:
            pass
        try:
            first = spotify.api_request("GET", "/me/tracks", token, params={"limit": 1, "offset": 0}).json()
            total = int(first.get("total") or 0)
            if total <= 0: return jsonify({"artists": [], "genres": [], "profiles": []})
            offsets = list(range(0, total, 50))
            artist_refs = {}
            for offset in random.sample(offsets, min(4, len(offsets))):
                page = spotify.api_request("GET", "/me/tracks", token, params={"limit": 50, "offset": offset}).json()
                for item in page.get("items") or []:
                    for artist in (item.get("track") or {}).get("artists") or []:
                        artist_id = str(artist.get("id") or "").strip(); name = str(artist.get("name") or "").strip()
                        if artist_id and name: artist_refs.setdefault(artist_id, name)
            sampled = list(artist_refs.items()); random.shuffle(sampled); sampled = sampled[:30]
            profiles = []; genre_counts = {}
            for _artist_id, name in sampled:
                genres = []; weighted_tags = []
                if lastfm.API_KEY:
                    try:
                        weighted_tags = lastfm.filtered_top_tags(name, min_weight=5, limit=6)
                        genres.extend(tag["name"] for tag in weighted_tags)
                    except (requests.RequestException, RuntimeError, ValueError):
                        pass
                if not genres: genres.extend(local_genres.get(name.casefold(), []))
                if not genres: continue
                for genre in genres: genre_counts[genre] = genre_counts.get(genre, 0) + 1
                profiles.append({"name": name, "genres": genres[:6], "tags": weighted_tags,
                                 "genre_source": "lastfm" if weighted_tags else "local"})
                if len(profiles) >= 18: break
            genres = [g for g, _ in sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:12]]
            return jsonify({"artists": [p["name"] for p in profiles], "genres": genres, "profiles": profiles,
                            "source": "liked-songs+lastfm"})
        except (requests.RequestException, spotify.SpotifyError) as exc:
            return jsonify({"artists": [], "genres": [], "profiles": [], "error": str(exc)}), 502

    ns["prompt_profile"] = prompt_profile
