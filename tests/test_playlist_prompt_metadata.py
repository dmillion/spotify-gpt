import unittest

from playlist_prompt_metadata import spotify_description, extract_prompt


class PromptMetadataTests(unittest.TestCase):
    def test_normal_prompt_is_round_trippable(self):
        prompt = "Create 20 instrumental stoner doom tracks with absolutely no vocals."
        output = spotify_description("Fuzzy cosmic riffs and heavy grooves.", prompt)
        self.assertTrue(output.startswith("Fuzzy cosmic riffs"))
        self.assertEqual(extract_prompt(output), prompt)
        self.assertLessEqual(len(output), 300)

    def test_long_prompt_is_marked_as_truncated(self):
        output = spotify_description("A dramatic playlist description.", "riff " * 100)
        self.assertLessEqual(len(output), 300)
        self.assertTrue(extract_prompt(output).endswith("…"))

    def test_no_prompt_does_not_invent_metadata(self):
        self.assertEqual(spotify_description("Just music", ""), "Just music")
        self.assertIsNone(extract_prompt("Just music"))


if __name__ == "__main__":
    unittest.main()
