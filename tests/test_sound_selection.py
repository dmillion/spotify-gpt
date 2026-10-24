import unittest

from sound_selection import filter_selection


class SoundSelectionTests(unittest.TestCase):
    def test_rejects_poor_measured_fit(self):
        chosen = [
            {"artist": "Slow Band", "title": "Slow Song"},
            {"artist": "Fast Band", "title": "Fast Song"},
            {"artist": "Unknown Band", "title": "Mystery"},
        ]
        candidates = [
            {"artist": "Slow Band", "title": "Slow Song", "musical_fit": 33.0},
            {"artist": "Fast Band", "title": "Fast Song", "musical_fit": 88.0},
            {"artist": "Unknown Band", "title": "Mystery", "musical_fit": None},
        ]
        kept, removed = filter_selection("driving upbeat psych rock", chosen, candidates)
        self.assertEqual([row["title"] for row in kept], ["Fast Song", "Mystery"])
        self.assertEqual(len(removed), 1)

    def test_no_sonic_request_does_not_filter(self):
        chosen = [{"artist": "Slow Band", "title": "Slow Song"}]
        candidates = [{"artist": "Slow Band", "title": "Slow Song", "musical_fit": 10}]
        self.assertEqual(filter_selection("songs about whiskey", chosen, candidates), (chosen, []))


if __name__ == "__main__":
    unittest.main()
