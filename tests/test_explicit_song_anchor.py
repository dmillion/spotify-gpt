import unittest
from unittest.mock import patch

import anchor_policy


PROMPT = "Give me more songs like 'Underneath You' by Frankie and the Witch Fingers, some driving upbeat psych rock with progression"


class AnchorPriorityTests(unittest.TestCase):
    def test_explicit_reference_is_parsed(self):
        req = anchor_policy._prompt_track_request(PROMPT)
        self.assertEqual((req.artist, req.title), ("Frankie and the Witch Fingers", "Underneath You"))

    def test_does_not_treat_artist_name_as_local_track_title(self):
        local = [{"artist": "Old Bones", "title": "The Witch", "genre": ""}]
        with patch.object(anchor_policy, "_spotify_prompt_anchor", return_value=None):
            found = anchor_policy._find_anchor(PROMPT, local)
        self.assertEqual((found["artist"], found["title"]),
                         ("Frankie and the Witch Fingers", "Underneath You"))
        self.assertEqual(found["anchor_type"], "song")

    def test_explicit_anchor_inserted_before_unrelated_curated_tracks(self):
        generated = {"description": "Upbeat psych rock.", "tracks": [
            {"artist": "Old Bones", "title": "The Witch"},
            {"artist": "Fuzz", "title": "What's In My Head?"},
        ]}
        with patch.object(anchor_policy, "_load_tracks", return_value=[
            {"artist": "Old Bones", "title": "The Witch", "genre": ""},
        ]):
            with patch.object(anchor_policy, "_spotify_prompt_anchor", return_value=None):
                result = anchor_policy.ensure_prompt_anchor(
                    PROMPT, generated, __import__("pathlib").Path("/unused"),
                    track_limit=20, artist_limit=2,
                )
        self.assertEqual(result["tracks"][0]["title"], "Underneath You")
        self.assertEqual(result["tracks"][0]["artist"], "Frankie and the Witch Fingers")


if __name__ == "__main__":
    unittest.main()
