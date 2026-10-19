import unittest
from unittest.mock import patch

import lrclib_client as lrclib
import vocal_policy as policy


class LRCLIBTests(unittest.TestCase):
    def setUp(self):
        policy.track_evidence.cache_clear()

    def test_exact_instrumental(self):
        row = {"id": 15, "artistName": "Band", "trackName": "Song",
               "albumName": "Record", "duration": 201, "instrumental": True,
               "plainLyrics": None, "syncedLyrics": None}
        with patch.object(lrclib, "request", return_value=row):
            self.assertEqual(lrclib.evidence("Band", "Song", "Record", 201)["status"], "instrumental")

    def test_missing_lyrics_is_not_instrumental(self):
        row = {"id": 15, "artistName": "Band", "trackName": "Song",
               "albumName": "Record", "duration": 201, "instrumental": False,
               "plainLyrics": None, "syncedLyrics": None}
        with patch.object(lrclib, "request", return_value=row):
            self.assertEqual(lrclib.evidence("Band", "Song", "Record", 201)["status"], "vocal")

    def test_mismatched_duration_rejected(self):
        row = {"id": 15, "artistName": "Band", "trackName": "Song",
               "albumName": "Record", "duration": 240, "instrumental": True}
        with patch.object(lrclib, "request", return_value=row):
            self.assertIsNone(lrclib.evidence("Band", "Song", "Record", 201))

    def test_alternate_release_album_with_matching_duration(self):
        row = {"id": 27, "artistName": "Band", "trackName": "Song",
               "albumName": "Original Album", "duration": 201,
               "instrumental": True, "plainLyrics": None, "syncedLyrics": None}
        with patch.object(lrclib, "request", return_value=[row]):
            result = lrclib.evidence("Band", "Song", "Deluxe Reissue", 201)
        self.assertEqual(result["status"], "instrumental")

    def test_alternate_album_without_duration_is_not_accepted(self):
        row = {"id": 27, "artistName": "Band", "trackName": "Song",
               "albumName": "Other Album", "duration": 201, "instrumental": True}
        with patch.object(lrclib, "request", return_value=[row]):
            self.assertIsNone(lrclib.evidence("Band", "Song", "Original Album"))

    def test_ambiguous_search_rejected(self):
        rows = [{"id": n, "artistName": "Band", "trackName": "Song",
                 "albumName": "Record", "duration": 201, "instrumental": flag}
                for n, flag in [(1, True), (2, False)]]
        with patch.object(lrclib, "request", return_value=rows):
            self.assertIsNone(lrclib.evidence("Band", "Song"))

    def test_resolved_uses_album_and_duration(self):
        track = {"artists": [{"name": "Band"}], "name": "Song",
                 "album": {"name": "Record"}, "duration_ms": 201000}
        with patch.object(policy, "track_evidence", return_value={"status":"unknown"}), patch.object(policy.lrclib_client, "evidence", return_value={"status":"instrumental", "source":"LRCLIB"}) as lookup:
            kept, rejected = policy.filter_tracks("instrumental only", [track], resolved=True)
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, [])
        lookup.assert_called_once_with("Band", "Song", "Record", 201.0)

    def test_vocal_metadata_not_overridden(self):
        track = {"artist": "Band", "title": "Song"}
        with patch.object(policy, "track_evidence", return_value={"status":"vocal"}), patch.object(policy.lrclib_client, "evidence") as lookup:
            kept, rejected = policy.filter_tracks("no vocals", [track])
        self.assertFalse(kept)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
