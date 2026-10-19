"""Recovery should search another pool, never write unverified recordings."""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

import app


class InstrumentalRecoveryTests(unittest.TestCase):
    def test_second_pool_is_checked_before_playlist_is_created(self):
        first = {"artist": "Band A", "title": "Unknown"}
        second = {"artist": "Band B", "title": "Verified"}
        generated = [
            {"name": "Heavy instrumentals", "description": "Test", "tracks": [first]},
            {"name": "Heavy instrumentals", "description": "Test", "tracks": [second]},
        ]
        def search(_token, req):
            artist = req.artist
            return {"uri": "spotify:track:" + artist, "name": req.title,
                    "artists": [{"name": artist}],
                    "album": {"name": "Record"}, "duration_ms": 200000}
        def evidence(_prompt, tracks, resolved=False):
            kept = [dict(t, instrumental_evidence={"status": "instrumental", "source": "test"})
                    for t in tracks if t["artists"][0]["name"] == "Band B"]
            return kept, ["Band A - Unknown (unknown)"] if len(kept) != len(tracks) else []

        with TemporaryDirectory() as temp, \
             patch.object(app, "DATABASE", Path(temp) / "history.sqlite"), \
             patch.object(app, "require_configuration"), \
             patch.object(app, "ask_for_hybrid_playlist", side_effect=generated) as curate, \
             patch.object(app.spotify, "get_access_token", return_value="token"), \
             patch.object(app.spotify, "search_track", side_effect=search), \
             patch("app_playlist_runtime.filter_tracks", side_effect=evidence), \
             patch("app_playlist_runtime.enforce_resolved", side_effect=lambda p,t: evidence(p,t,True)), \
             patch.object(app.spotify, "create_playlist", return_value={"id":"test","name":"Heavy instrumentals"}) as create, \
             patch.object(app.spotify, "add_items") as add:
            result = app.create_from_prompt("20 instrumental stoner rock tracks. No vocals")
        self.assertEqual(curate.call_count, 2)
        create.assert_called_once()
        self.assertEqual(add.call_args.args[2], ["spotify:track:Band B"])
        self.assertEqual(len(result["tracks"]), 1)


if __name__ == "__main__":
    unittest.main()
