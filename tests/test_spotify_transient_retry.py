"""Spotify GET retry behavior without live network calls."""
import unittest
from unittest.mock import Mock, patch

import spotify_playlist as spotify


class SpotifyTransientRetryTests(unittest.TestCase):
    def test_search_recovers_after_503(self):
        unavailable = Mock(status_code=503, reason="Service Unavailable")
        unavailable.json.return_value = {"error": {"message": "Service Unavailable"}}
        success = Mock(status_code=200)
        success.json.return_value = {"tracks": {"items": []}}
        with patch.object(spotify.requests, "request", side_effect=[unavailable, success]) as request, \
             patch.object(spotify.time, "sleep") as sleep:
            response = spotify.api_request("GET", "/search", "token",
                                           params={"q": "test", "type": "track"})
        self.assertIs(response, success)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_search_exhausts_retries(self):
        unavailable = Mock(status_code=503, reason="Service Unavailable")
        unavailable.json.return_value = {"error": {"message": "Service Unavailable"}}
        with patch.object(spotify.requests, "request", return_value=unavailable) as request, \
             patch.object(spotify.time, "sleep") as sleep:
            with self.assertRaises(spotify.SpotifyError):
                spotify.api_request("GET", "/search", "token")
        self.assertEqual(request.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4])

    def test_post_is_not_retried_on_503(self):
        unavailable = Mock(status_code=503, reason="Service Unavailable")
        unavailable.json.return_value = {"error": {"message": "Service Unavailable"}}
        with patch.object(spotify.requests, "request", return_value=unavailable) as request:
            with self.assertRaises(spotify.SpotifyError):
                spotify.api_request("POST", "/playlists", "token")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
