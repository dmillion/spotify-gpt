import unittest

from refinement_constraints import excluded_artists, filter_removed


class RefinementConstraintsTests(unittest.TestCase):
    def setUp(self):
        self.published = [
            {"artist": "Frankie and the Witch Fingers", "title": "Dracula Drug"},
            {"artist": "Thee Oh Sees", "title": "Toe Cutter - Thumb Buster"},
            {"artist": "Psychedelic Porn Crumpets", "title": "Hymn For A Droid"},
            {"artist": "Hooveriii", "title": "See"},
            {"artist": "Red Fang", "title": "Failure"},
            {"artist": "Black Moth", "title": "Stinkhorn"},
            {"artist": "Clutch", "title": "The Devil & Me"},
            {"artist": "Orange Goblin", "title": "Snail Hook"},
        ]
        self.request = "remove red fang, clutch, and orange goblin, find more like the others"

    def test_artist_removals_override_model(self):
        retained, _, removed, blocked = filter_removed(self.request, self.published)
        self.assertEqual(len(retained), 5)
        self.assertEqual({row["artist"] for row in removed},
                         {"Red Fang", "Clutch", "Orange Goblin"})
        self.assertEqual(blocked, {"red fang", "clutch", "orange goblin"})

    def test_new_discoveries_cannot_reintroduce_removed_artists(self):
        additions = [
            {"artist": "Clutch", "title": "Another Song"},
            {"artist": "Orange Goblin", "title": "New Song"},
            {"artist": "The Mystery Lights", "title": "New Psych Song"},
        ]
        _, allowed, _, _ = filter_removed(self.request, self.published, additions)
        self.assertEqual([row["artist"] for row in allowed], ["The Mystery Lights"])

    def test_nonremoval_prompt_does_not_filter_artists(self):
        self.assertEqual(excluded_artists("find more like Clutch", self.published), set())


if __name__ == "__main__":
    unittest.main()
