"""Step 3 discovery novelty regression tests."""
import unittest
from unittest.mock import patch

import artist_similarity_integration as discovery


class DiscoveryStep3Tests(unittest.TestCase):
    def test_repeat_penalty_prefers_fresh_recording(self):
        rows = [
            {"artist": "Old Band", "title": "Old Song", "match": .95},
            {"artist": "Fresh Band", "title": "New Song", "match": .75},
        ]
        from collections import Counter
        with patch.object(discovery, "_history", return_value=(
            Counter({("old band", "old song"): 2}),
            Counter({"old band": 2}),
        )):
            selected = discovery._novelty_order(rows, "heavy psych rock", limit=2)
        self.assertEqual(selected[0]["artist"], "Fresh Band")

    def test_no_history_keeps_stronger_match(self):
        from collections import Counter
        rows = [
            {"artist": "Strong", "title": "A", "match": .9},
            {"artist": "Weak", "title": "B", "match": .2},
        ]
        with patch.object(discovery, "_history", return_value=(Counter(), Counter())):
            selected = discovery._novelty_order(rows, "heavy psych rock", limit=2)
        self.assertEqual(selected[0]["artist"], "Strong")

    def test_artist_cap_and_duplicate_tracks(self):
        from collections import Counter
        rows = [
            {"artist": "A", "title": "One", "match": .9},
            {"artist": "A", "title": "One", "match": .9},
            {"artist": "A", "title": "Two", "match": .8},
            {"artist": "A", "title": "Three", "match": .7},
            {"artist": "B", "title": "Four", "match": .6},
        ]
        with patch.object(discovery, "_history", return_value=(Counter(), Counter())):
            selected = discovery._novelty_order(rows, "heavy psych rock", limit=10)
        self.assertEqual([(r["artist"], r["title"]) for r in selected],
                         [("A", "One"), ("A", "Two"), ("B", "Four")])

    def test_reference_tracks_not_consumed_from_discovery_budget(self):
        from collections import Counter
        prompt = "songs like 'Underneath You' by Frankie and the Witch Fingers"
        rows = [
            {"artist": "Frankie and the Witch Fingers", "title": "Underneath You", "match": 1},
            {"artist": "Other", "title": "New", "match": .8},
        ]
        with patch.object(discovery, "_history", return_value=(Counter(), Counter())):
            selected = discovery._novelty_order(rows, prompt, limit=2)
        self.assertEqual([r["title"] for r in selected], ["New"])


if __name__ == "__main__":
    unittest.main()
