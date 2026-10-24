import unittest
from unittest.mock import patch

import bandcamp_discovery


class BandcampReferenceTests(unittest.TestCase):
    def test_only_approved_https_bandcamp_hosts(self):
        details = {"relations": [
            {"target-type": "url", "url": {"resource": "https://example.bandcamp.com/"}},
            {"target-type": "url", "url": {"resource": "https://bandcamp.com/example"}},
            {"target-type": "url", "url": {"resource": "https://fakebandcamp.com/foo"}},
            {"target-type": "url", "url": {"resource": "http://example.bandcamp.com/"}},
            {"target-type": "url", "url": {"resource": "https://example.bandcamp.com/"}},
        ]}
        self.assertEqual(bandcamp_discovery.bandcamp_links(details),
                         ["https://example.bandcamp.com/", "https://bandcamp.com/example"])

    def test_discovery_requires_artist_bandcamp_reference(self):
        def details(name):
            return {"relations": [{
                "target-type": "url",
                "url": {"resource": "https://someband.bandcamp.com/"}
            }]} if name == "Some Band" else {"relations": []}
        with patch.object(bandcamp_discovery.musicbrainz, "artist_details", side_effect=details):
            with patch.object(bandcamp_discovery.musicbrainz, "recordings_by_artist",
                              return_value=[
                                  {"artist": "Some Band", "title": "Song One"},
                                  {"artist": "Some Band", "title": "Song Two"},
                              ]) as recordings:
                rows = bandcamp_discovery.discover(["Other Band", "Some Band"],
                                                   ["Some Band - Song One"])
        self.assertEqual([r["title"] for r in rows], ["Song Two"])
        self.assertEqual(rows[0]["source"], "bandcamp-reference")
        recordings.assert_called_once()

    def test_no_scraping_or_audio_access(self):
        with patch.object(bandcamp_discovery.musicbrainz, "artist_details",
                          return_value={"relations": []}):
            with patch.object(bandcamp_discovery.musicbrainz, "recordings_by_artist") as recordings:
                self.assertEqual(bandcamp_discovery.discover(["No Link"]), [])
                recordings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
