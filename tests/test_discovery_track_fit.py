"""Tests for evidence-aware external discovery and soft artist limits."""
import unittest
from collections import Counter
from unittest.mock import patch

import artist_similarity_integration as discovery
import discovery_track_fit


class DiscoveryTrackFitTests(unittest.TestCase):
    def test_fast_abrasive_tags_beat_mellow_track(self):
        prompt = "fast abrasive heavy psychedelic rock"
        with patch.object(discovery_track_fit.sonic_ranking, "track_tags",
                          side_effect=[("fast", "fuzzy", "driving"),
                                       ("slow", "mellow", "ambient")]):
            good, _ = discovery_track_fit.adjustment(prompt, "Band", "Fast")
            poor, _ = discovery_track_fit.adjustment(prompt, "Band", "Slow")
        self.assertGreater(good, poor)
        self.assertLess(poor, 0)

    def test_soft_cap_allows_more_when_diversity_exhausted(self):
        rows = [{"artist": "Band A", "title": str(i), "match": .8} for i in range(4)]
        rows += [{"artist": "Band B", "title": "One", "match": .7}]
        with patch.object(discovery, "_history", return_value=(Counter(), Counter())), \\
             patch.object(discovery.discovery_track_fit, "adjustment", return_value=(0, {})):
            result = discovery._novelty_order(rows, "fast psych rock", limit=5)
        self.assertEqual(len(result), 5)
        self.assertIn("Band B", [row["artist"] for row in result])
        self.assertEqual(sum(row["artist"] == "Band A" for row in result), 4)

    def test_artist_similarity_does_not_override_track_fit(self):
        rows = [
            {"artist": "Popular", "title": "Slow", "match": .95},
            {"artist": "Less Similar", "title": "Fast", "match": .5},
        ]
        def fit(prompt, artist, title):
            return (-20, {}) if title == "Slow" else (20, {})
        with patch.object(discovery, "_history", return_value=(Counter(), Counter())), \\
             patch.object(discovery.discovery_track_fit, "adjustment", side_effect=fit):
            result = discovery._novelty_order(rows, "fast abrasive rock", limit=2)
        self.assertEqual(result[0]["title"], "Fast")


if __name__ == "__main__":
    unittest.main()
