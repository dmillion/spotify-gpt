import unittest
from unittest.mock import patch

import lyric_theme


class LyricalIntentTests(unittest.TestCase):
    def test_theme_requests_are_explicit(self):
        self.assertTrue(lyric_theme.intent("Find me songs in stoner/sludge/doom metal about whiskey"))
        self.assertTrue(lyric_theme.intent("Find me songs in that genre about whiskey"))
        self.assertTrue(lyric_theme.intent("Find rock songs that mention whiskey in the lyrics"))
        self.assertEqual(lyric_theme.subject("Find me songs in that genre about whiskey"), "whiskey")

    def test_normal_prompts_are_unchanged(self):
        for prompt in ("dark stoner doom", "whiskey-soaked blues rock",
                       "instrumental stoner rock and doom, absolutely no vocals"):
            self.assertFalse(lyric_theme.intent(prompt))

    def test_unavailable_lyrics_are_not_accepted(self):
        track = {"name": "Song", "artists": [{"name": "Band"}]}
        with patch.object(lyric_theme, "lyrics_for_track", return_value=None):
            accepted, rejected = lyric_theme.verify("songs about whiskey", [track],
                                                     lambda *a, **kw: {"matches": True})
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)

    def test_semantic_lyrics_matching(self):
        track = {"name": "Song", "artists": [{"name": "Band"}]}
        calls = []
        def model(system, user, schema, **kwargs):
            calls.append(user)
            return {"matches": True}
        with patch.object(lyric_theme, "lyrics_for_track",
                          return_value={"text": "A bottle and whiskey all night",
                                        "source": "https://lrclib.net/api/get/1"}):
            accepted, _ = lyric_theme.verify("songs about whiskey", [track], model)
        self.assertEqual(len(accepted), 1)
        self.assertIn("whiskey", calls[0])


if __name__ == "__main__":
    unittest.main()
