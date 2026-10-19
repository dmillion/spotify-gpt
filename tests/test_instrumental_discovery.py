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
