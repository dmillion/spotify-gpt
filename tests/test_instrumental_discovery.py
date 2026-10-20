import unittest
from unittest.mock import Mock

import instrumental_discovery


class InstrumentalFirstTests(unittest.TestCase):
    def test_heavy_prompt_uses_instrumental_scene_seeds(self):
        queries = instrumental_discovery._search_queries(
            "Create a playlist of 20 instrumental stoner rock and psychedelic doom tracks. Absolutely no vocals."
        )
        self.assertIn('artist:"Karma to Burn"', queries)
        self.assertIn('artist:"Belzebong"', queries)
        self.assertNotIn('artist:"Tycho"', queries)

    def test_unknown_style_does_not_force_heavy_artists(self):
        queries = instrumental_discovery._search_queries("instrumental classical piano")
        self.assertFalse(any(q.startswith('artist:"') for q in queries))

    def test_discovery_interleaves_artists_before_candidate_limit(self):
        def response(method, path, token, **kwargs):
            query = kwargs["params"]["q"]
            artist = query.split('"')[1] if query.startswith('artist:"') else "Other"
            tracks = [{"uri": "spotify:track:" + artist + str(i), "name": str(i),
                       "artists": [{"name": artist}]} for i in range(10)]
            result = Mock()
            result.json.return_value = {"tracks": {"items": tracks}}
            return result

        api = Mock()
        api.api_request.side_effect = response
        tracks = instrumental_discovery.discover("token", api, "instrumental stoner doom", limit=12)
        artists = [track["artists"][0]["name"] for track in tracks]
        self.assertEqual(len(tracks), 12)
        self.assertEqual(len(set(artists)), 12)

    def test_spotify_results_are_only_candidates_not_verified(self):
        track = {"uri": "spotify:track:1", "name": "A Song",
                 "artists": [{"name": "Belzebong"}], "duration_ms": 123000}
        api = Mock()
        api.api_request.return_value.json.return_value = {
            "tracks": {"items": [track, track]}}
        results = instrumental_discovery.discover(
            "token", api, "instrumental stoner rock", limit=5
        )
        self.assertEqual(results, [track])
        self.assertNotIn("instrumental_evidence", results[0])


if __name__ == "__main__":
    unittest.main()
