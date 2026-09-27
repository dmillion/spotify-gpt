"""Read the current Spotify playlist before iterative Tune Raider actions."""
from __future__ import annotations

import re


def playlist_id_from_url(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"open\.spotify\.com/playlist/([A-Za-z0-9]+)", text)
    return match.group(1) if match else ""


def _track_record(track: dict) -> dict | None:
    if not isinstance(track, dict):
        return None
    title = str(track.get("name") or "").strip()
    artists = [str(artist.get("name") or "").strip() for artist in track.get("artists") or []]
    artists = [artist for artist in artists if artist]
    if not title or not artists:
        return None
    return {
        "artist": ", ".join(artists),
        "title": title,
        "uri": str(track.get("uri") or "").strip(),
        "url": (track.get("external_urls") or {}).get("spotify"),
    }


def fetch_playlist_tracks(spotify, token: str, spotify_url: str) -> tuple[str, list[dict]]:
    """Return playlist id and its current Spotify track list, including manual edits."""
    playlist_id = playlist_id_from_url(spotify_url)
    if not playlist_id:
        raise spotify.SpotifyError("Could not determine the Spotify playlist id from local history.")

    tracks: list[dict] = []
    offset = 0
    while True:
        response = spotify.api_request(
            "GET",
            f"/playlists/{playlist_id}/items",
            token,
            params={"limit": 100, "offset": offset},
        ).json()
        items = response.get("items") or []
        for row in items:
            track = row.get("track") or row.get("item") or {}
            record = _track_record(track)
            if record:
                tracks.append(record)
        offset += len(items)
        total = int(response.get("total") or 0)
        if not items or offset >= total:
            break
    return playlist_id, tracks


def normalized_key(spotify, track: dict) -> tuple[str, str]:
    return (
        spotify.normalize(str(track.get("artist") or "")),
        spotify.normalize(str(track.get("title") or "")),
    )


def compare_stored_to_live(spotify, stored: list[dict], live: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (manual_removals, manual_additions) relative to the stored snapshot."""
    stored_map = {normalized_key(spotify, track): track for track in stored if all(normalized_key(spotify, track))}
    live_map = {normalized_key(spotify, track): track for track in live if all(normalized_key(spotify, track))}
    removed = [track for key, track in stored_map.items() if key not in live_map]
    added = [track for key, track in live_map.items() if key not in stored_map]
    return removed, added


def as_exclusions(tracks: list[dict]) -> list[str]:
    return [
        f"{track.get('artist', '')} - {track.get('title', '')}"
        for track in tracks
        if track.get("artist") and track.get("title")
    ]
