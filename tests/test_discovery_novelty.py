"""Regression checks for canonical identities and historical recommendation novelty."""
import json
import sqlite3
import unittest

from discovery_novelty import artist_key, curate, history_counts, track_key

PROMPT = ("HYBRID / FIND SOME MORE SONGS LIKE 'UNDERNEATH YOU' OR "
          "'DRACULA DRUG' BY FRANKIE AND THE WITCH FINGERS, "
          "LONG HEAVY PSYCH ROCK, ABRASIVE AND FAST TEMPO")


def track(artist, title):
    return {"artist": artist, "title": title}


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE generated_playlists (tracks TEXT)")
        self.db.execute("INSERT INTO generated_playlists VALUES (?)", (json.dumps([
            track("Thee Oh Sees", "Nite Expo"),
            track("Meatbodies", "Him"),
        ]),))

    def tearDown(self):
        self.db.close()

    def test_aliases_share_artist_identity(self):
        self.assertEqual(artist_key("Osees, Thee Oh Sees"), artist_key("Thee Oh Sees"))
        self.assertEqual(artist_key("Osees"), artist_key("Thee Oh Sees"))

    def test_history_tracks_aliases(self):
        counts, _ = history_counts(self.db)
        self.assertEqual(counts[track_key(track("Osees", "Nite Expo"))], 1)

    def test_references_survive_and_repeats_rank_later(self):
        generated = {"tracks": [
            track("Frankie and the Witch Fingers", "Underneath You"),
            track("Frankie and the Witch Fingers", "Dracula Drug"),
            track("Osees", "Nite Expo"),
            track("Meatbodies", "Him"),
            track("Wine Lips", "Mall Walker"),
        ]}
        result = curate(PROMPT, generated, self.db)
        titles = [item["title"] for item in result["tracks"]]
        self.assertEqual(titles[:2], ["Underneath You", "Dracula Drug"])
        self.assertEqual(titles[2], "Mall Walker")

    def test_aliases_respect_artist_limit(self):
        generated = {"tracks": [
            track("Osees", "A"), track("Thee Oh Sees", "B"),
            track("Osees, Thee Oh Sees", "C"),
        ]}
        result = curate("garage rock", generated, self.db, artist_limit=2)
        self.assertEqual(len(result["tracks"]), 2)


if __name__ == "__main__":
    unittest.main()
