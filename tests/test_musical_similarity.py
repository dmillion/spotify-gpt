import unittest

from musical_similarity import acoustic_fit, emphasis, rank


class MusicalSimilarityTests(unittest.TestCase):
    def test_explicit_prompt_weights_performance_axes(self):
        flags = emphasis("driving upbeat psych rock with heavy guitar riffs and progression")
        self.assertTrue(flags["tempo"])
        self.assertTrue(flags["rhythmic_density"])
        self.assertTrue(flags["loudness"])
        self.assertTrue(flags["low_mid_weight"])
        self.assertTrue(flags["progression"])

    def test_weighted_acoustic_fit_prioritizes_rhythm_and_tempo(self):
        targets = {"tempo": 85, "rhythmic_density": 85, "bass_weight": 50}
        fast = {"sound": {"tempo": 85, "rhythmic_density": 85, "bass_weight": 0}}
        slow = {"sound": {"tempo": 15, "rhythmic_density": 15, "bass_weight": 50}}
        prompt = "driving upbeat rock"
        self.assertGreater(acoustic_fit(fast, targets, prompt),
                           acoustic_fit(slow, targets, prompt))

    def test_unknown_external_audio_is_not_fabricated(self):
        candidates = [{"artist": "Unknown", "title": "X", "source": "lastfm"},
                      {"artist": "Measured", "title": "Y", "source": "local",
                       "sound": {"tempo": 81, "rhythmic_density": 86}}]
        ranked = rank(candidates, {"artists": [], "terms": [],
                                   "sound": {"tempo": 80, "rhythmic_density": 85}},
                      "upbeat driving rock")
        external = next(c for c in ranked if c["artist"] == "Unknown")
        self.assertIsNone(external["musical_fit"])
        self.assertEqual(ranked[0]["artist"], "Measured")

    def test_prompt_without_acoustic_constraints_keeps_unknown_as_unknown(self):
        self.assertEqual(emphasis("melancholy indie rock"), {})
        self.assertIsNone(acoustic_fit({"artist": "X"}, {"tempo": 70}, "rock"))


if __name__ == "__main__":
    unittest.main()
