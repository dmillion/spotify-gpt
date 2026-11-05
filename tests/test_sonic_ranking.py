"""Track-level scoring regression tests; no external requests."""
import unittest
from unittest.mock import patch

import sonic_ranking


def recording(artist, title, minutes):
    return {"artists": [{"name": artist}], "name": title,
            "duration_ms": minutes * 60000, "uri": f"spotify:track:{title}"}


PROMPT = ("FIND SONGS LIKE 'UNDERNEATH YOU' OR 'DRACULA DRUG' "
          "BY FRANKIE AND THE WITCH FINGERS, LONG HEAVY PSYCH ROCK, "
          "ABRASIVE AND FAST TEMPO")


class SonicRankingTests(unittest.TestCase):
    def test_prompt_dimensions(self):
        dimensions = sonic_ranking.intent(PROMPT)
        self.assertTrue(all(dimensions.values()))

    def test_recording_tags_and_duration(self):
        fast = recording("Example", "Fast", 7)
        slow = recording("Example", "Slow", 2)
        fast_score, evidence = sonic_ranking.score(
            PROMPT, fast, tags=["fast", "fuzzy", "psychedelic rock", "driving"])
        slow_score, _ = sonic_ranking.score(PROMPT, slow, tags=["garage rock"])
        self.assertGreater(fast_score, slow_score)
        self.assertEqual(evidence["duration"], 7)

    def test_reference_tracks_remain_first(self):
        tracks = [
            recording("Other", "Fast", 7),
            recording("Frankie and the Witch Fingers", "Dracula Drug", 4),
            recording("Frankie and the Witch Fingers", "Underneath You", 4),
        ]
        with patch.object(sonic_ranking, "track_tags", return_value=("fast", "heavy")):
            result = sonic_ranking.rank(PROMPT, tracks)
        self.assertEqual([t["name"] for t in result[:2]],
                         ["Dracula Drug", "Underneath You"])

    def test_missing_evidence_does_not_invent_tempo(self):
        score, evidence = sonic_ranking.score(
            PROMPT, recording("Unknown", "Unknown", 4), tags=[])
        self.assertNotIn("speed", evidence)
        self.assertNotIn("drive", evidence)
        self.assertGreaterEqual(score, 0)


if __name__ == "__main__":
    unittest.main()
