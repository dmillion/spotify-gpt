import unittest
from unittest.mock import patch

import instrumental_web_evidence as online
import vocal_policy as policy


class InstrumentalOnlineEvidenceTests(unittest.TestCase):
    def setUp(self):
        policy.track_evidence.cache_clear()

    def test_unconfigured_search_does_nothing(self):
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": ""}):
            self.assertIsNone(online.search_instrumental("Artist", "Track"))

    def test_explicit_track_specific_version_can_be_verified(self):
        hit = {"web": {"results": [{
            "title": "Artist - Track (Instrumental Version) | Bandcamp",
            "description": "Track by Artist",
            "url": "https://example.bandcamp.com/track/track",
        }]}}
        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "fake"}), patch.object(online.requests, "get") as get:
            get.return_value.json.return_value = hit
            get.return_value.raise_for_status.return_value = None
            evidence = online.search_instrumental("Artist", "Track")
        self.assertEqual(evidence["status"], "instrumental")
        self.assertIn("bandcamp.com", evidence["source"])

    def test_artist_genre_or_unrelated_title_are_not_evidence(self):
        for heading in ["Artist - Track | Instrumental rock | Bandcamp",
                        "Artist - Other Song (Instrumental Version) | Bandcamp"]:
            hit = {"web": {"results": [{"title": heading,
                "description": "Artist instrumental music",
                "url": "https://artist.bandcamp.com/track/example"}]}}
            with self.subTest(heading=heading), patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "fake"}), patch.object(online.requests, "get") as get:
                get.return_value.json.return_value = hit
                self.assertIsNone(online.search_instrumental("Artist", "Track"))

    def test_unknown_metadata_invokes_search(self):
        with patch.object(policy, "_lastfm_evidence", return_value=None), patch.object(policy, "_musicbrainz_evidence", return_value=None), patch.object(policy.instrumental_web_evidence, "search_instrumental", return_value={"status": "instrumental", "source": "https://a.bandcamp.com/track/t"}) as lookup:
            self.assertEqual(policy.track_evidence("A", "T")["status"], "instrumental")
            lookup.assert_called_once_with("A", "T")

    def test_vocal_evidence_overrides_online_search(self):
        with patch.object(policy, "_lastfm_evidence", return_value={"status":"vocal","source":"Last.fm"}), patch.object(policy.instrumental_web_evidence, "search_instrumental") as lookup:
            self.assertEqual(policy.track_evidence("A", "T")["status"], "vocal")
            lookup.assert_not_called()

    def test_search_failure_does_not_admit_unknown(self):
        with patch.object(policy, "_lastfm_evidence", return_value=None), patch.object(policy, "_musicbrainz_evidence", return_value=None), patch.object(policy.instrumental_web_evidence, "search_instrumental", side_effect=online.requests.Timeout):
            self.assertEqual(policy.track_evidence("A", "T")["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
