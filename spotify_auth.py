"""Spotify authorization health checks and silent recovery helpers."""
from __future__ import annotations

import requests

import spotify_playlist as spotify


class SpotifyAuthorizationRequired(spotify.SpotifyError):
    """Raised when cached Spotify authorization cannot be recovered silently."""


def cached_access_token() -> str | None:
    """Return a usable cached token, refreshing silently when possible.

    This function never launches interactive OAuth.
    """
    token = spotify.load_token()
    if not token or not spotify.token_has_required_scopes(token):
        return None
    access_token = str(token.get("access_token") or "").strip()
    if not access_token:
        return None
    return access_token


def auth_status(*, verify: bool = True) -> dict:
    """Describe whether Spotify can be used without interactive authorization."""
    if not spotify.CLIENT_ID:
        return {
            "authorized": False,
            "reauthorize": True,
            "reason": "Spotify is not configured. Add SPOTIFY_CLIENT_ID to .env.",
        }

    token = spotify.load_token()
    if not token:
        return {
            "authorized": False,
            "reauthorize": True,
            "reason": "Spotify authorization is required on this machine.",
        }
    if not spotify.token_has_required_scopes(token):
        return {
            "authorized": False,
            "reauthorize": True,
            "reason": "Spotify permissions changed and authorization must be renewed.",
        }

    access_token = str(token.get("access_token") or "").strip()
    if not access_token:
        return {
            "authorized": False,
            "reauthorize": True,
            "reason": "Spotify authorization could not be refreshed.",
        }

    if verify:
        try:
            response = requests.get(
                f"{spotify.API_BASE}/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
        except requests.RequestException as exc:
            return {
                "authorized": False,
                "reauthorize": False,
                "temporary": True,
                "reason": f"Spotify authorization could not be verified: {exc}",
            }

        if response.status_code == 401:
            raw = spotify._read_token_file()
            if raw and raw.get("refresh_token"):
                try:
                    refreshed = spotify.refresh_access_token(raw)
                except requests.RequestException:
                    refreshed = None
                if refreshed and refreshed.get("access_token"):
                    access_token = str(refreshed["access_token"])
                    retry = requests.get(
                        f"{spotify.API_BASE}/me",
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=15,
                    )
                    if retry.ok:
                        return {"authorized": True, "reauthorize": False, "refreshed": True}
            return {
                "authorized": False,
                "reauthorize": True,
                "reason": "Spotify rejected the cached authorization. Reconnect Spotify.",
            }
        if response.status_code == 403:
            return {
                "authorized": False,
                "reauthorize": True,
                "reason": "Spotify authorization no longer has the required permissions.",
            }
        if not response.ok:
            return {
                "authorized": False,
                "reauthorize": False,
                "temporary": True,
                "reason": f"Spotify authorization check returned HTTP {response.status_code}.",
            }

    return {"authorized": True, "reauthorize": False}


def require_authorized() -> str:
    status = auth_status(verify=True)
    if not status.get("authorized"):
        if status.get("temporary"):
            raise spotify.SpotifyError(str(status.get("reason") or "Spotify is temporarily unavailable."))
        raise SpotifyAuthorizationRequired(str(status.get("reason") or "Spotify authorization is required."))
    token = cached_access_token()
    if not token:
        raise SpotifyAuthorizationRequired("Spotify authorization is required.")
    return token


_original_api_request = spotify.api_request


def api_request_with_auth_retry(method: str, path: str, token: str, **kwargs):
    """Retry one Spotify API request after a silent token refresh on HTTP 401."""
    try:
        return _original_api_request(method, path, token, **kwargs)
    except requests.HTTPError as exc:
        response = exc.response
        if response is None or response.status_code != 401:
            raise

        raw = spotify._read_token_file()
        if not raw or not raw.get("refresh_token"):
            raise SpotifyAuthorizationRequired("Spotify authorization expired. Reconnect Spotify.") from exc
        refreshed = spotify.refresh_access_token(raw)
        if not refreshed or not refreshed.get("access_token"):
            raise SpotifyAuthorizationRequired("Spotify authorization expired. Reconnect Spotify.") from exc
        return _original_api_request(method, path, str(refreshed["access_token"]), **kwargs)


def install_auth_retry() -> None:
    if spotify.api_request is not api_request_with_auth_retry:
        spotify.api_request = api_request_with_auth_retry
