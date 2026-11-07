"""Spotify resolution fallback regression tests; all API responses are mocked."""
import unittest
from unittest.mock import patch

import spotify_playlist as spotify


def track(artist, title, identity):
    return {"id": identity, "name": title, "artists": [{"name": artist}]}


class SpotifySearchFallbackTests(unittest.TestCase):
    def test_fallback_resolves_matching_artist_and_title(self):
        requested = spotify.TrackRequest("King Gizzard & The Lizard Wizard", "Robot Stop")
        calls = []
        def search(method, path, token, params):
            calls.append(params["q"])
            items = ([track(requested.artist, requested.title, "robot")]
                     if params["q"] == 'track:"Robot Stop"' else [])
            return type("Response", (), {"json": lambda self: {"tracks": {"items": items}}})()
        with patch.object(spotify, "api_request", side_effect=search):
            result = spotify.search_track("token", requested)
        self.assertEqual(result["id"], "robot")
        self.assertEqual(len(calls), 3)

    def test_fallback_rejects_wrong_artist(self):
        requested = spotify.TrackRequest("King Gizzard & The Lizard Wizard", "Robot Stop")
        def search(method, path, token, params):
            items = ([track("Other Band", "Robot Stop", "cover")]
                     if params["q"] == 'track:"Robot Stop"' else [])
            return type("Response", (), {"json": lambda self: {"tracks": {"items": items}}})()
        with patch.object(spotify, "api_request", side_effect=search):
            self.assertIsNone(spotify.search_track("token", requested))

    def test_successful_primary_search_skips_fallback(self):
        requested = spotify.TrackRequest("Band", "Song")
        with patch.object(spotify, "api_request") as request:
            request.return_value.json.return_value = {
                "tracks": {"items": [track("Band", "Song", "exact")]}}
            result = spotify.search_track("token", requested)
        self.assertEqual(result["id"], "exact")
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
