import sqlite3
import unittest
from unittest.mock import Mock

import spotify_history_reconcile as reconcile


class SpotifyHistoryReconcileTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE generated_playlists "
                        "(id INTEGER PRIMARY KEY, name TEXT, spotify_url TEXT)")
        self.db.executemany(
            "INSERT INTO generated_playlists VALUES (?,?,?)",
            [(1, "Psych Rock Progression", "https://open.spotify.com/playlist/deleted123"),
             (2, "Psych Rock Progression", "https://open.spotify.com/playlist/present456")],
        )

    def tearDown(self):
        self.db.close()

    def test_identical_names_do_not_collide(self):
        spotify = Mock()
        def request(method, path, token, **kwargs):
            if path == "/me/playlists":
                return Mock(status_code=200, json=lambda: {
                    "total": 1, "items": [{"id": "present456"}]
                })
            if path == "/playlists/deleted123":
                raise spotify.SpotifyError("Spotify API HTTP 404 on GET /playlists/deleted123: Not found")
            raise AssertionError(path)
        spotify.SpotifyError = type("SpotifyError", (Exception,), {})
        spotify.api_request.side_effect = request
        rows = self.db.execute("SELECT id, name, spotify_url FROM generated_playlists").fetchall()
        with self.db:
            removed = reconcile.archive_missing(
                self.db, rows, spotify, "token",
                lambda url: url.rsplit("/", 1)[-1],
            )
        self.assertEqual(removed, 1)
        self.assertEqual([r["id"] for r in self.db.execute(
            "SELECT id FROM generated_playlists").fetchall()], [2])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM spotify_history_archive").fetchone()[0], 1)

    def test_matching_name_count_keeps_history_even_with_different_ids(self):
        spotify = Mock()
        spotify.api_request.return_value = Mock(
            status_code=200, json=lambda: {"total": 2, "items": [
                {"id": "other111", "name": "Psych Rock Progression"},
                {"id": "other222", "name": "Psych Rock Progression"},
            ]}
        )
        rows = self.db.execute("SELECT id, name, spotify_url FROM generated_playlists").fetchall()
        with self.db:
            removed = reconcile.archive_missing(
                self.db, rows, spotify, "token",
                lambda url: url.rsplit("/", 1)[-1],
            )
        self.assertEqual(removed, 0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM generated_playlists").fetchone()[0], 2)

    def test_incomplete_snapshot_does_not_remove_anything(self):
        spotify = Mock()
        spotify.api_request.return_value = Mock(
            status_code=200, json=lambda: {"total": 2, "items": [{"id": "present456", "name": "Psych Rock Progression"}]}
        )
        with self.assertRaises(ValueError):
            reconcile.archive_missing(
                self.db,
                self.db.execute("SELECT id, spotify_url FROM generated_playlists").fetchall(),
                spotify, "token", lambda url: url.rsplit("/", 1)[-1],
            )
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM generated_playlists").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
