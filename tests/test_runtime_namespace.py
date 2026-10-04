import unittest

import app
import app_bootstrap
from anchor_policy import _ground_description, _prompt_artist_name


class RuntimeNamespaceTests(unittest.TestCase):
    def test_app_is_bootstrap_module(self):
        self.assertIs(app, app_bootstrap)

    def test_tune_it_up_possessive_artist_anchor(self):
        prompt = (
            "Start with DILLY DALLY's garage rock side and build toward "
            "a half-empty dive bar; tense and rhythm-forward, stay rough around the edges."
        )
        self.assertEqual(_prompt_artist_name(prompt), "DILLY DALLY")

    def test_tune_it_up_possessive_handles_artist_apostrophe(self):
        prompt = (
            "Start with Jane's Addiction's alternative rock side and build toward "
            "a sweaty club; raw and kinetic, avoid slick production."
        )
        self.assertEqual(_prompt_artist_name(prompt), "Jane's Addiction")

    def test_tune_it_up_around_form_stops_at_colon(self):
        prompt = (
            "Build a garage rock playlist around DILLY DALLY: "
            "tense and rhythm-forward; stay rough around the edges."
        )
        self.assertEqual(_prompt_artist_name(prompt), "DILLY DALLY")

    def test_grounded_description_keeps_prompt_style_and_anchor(self):
        prompt = (
            "Start with DILLY DALLY's garage rock side and build toward "
            "a half-empty dive bar; tense and rhythm-forward, stay rough around the edges."
        )
        generated = {
            "description": "Anchored by a missing unrelated artist.",
            "tracks": [
                {"artist": "DILLY DALLY", "title": "Desire"},
                {"artist": "Pip Blom", "title": "School"},
            ],
        }
        catalog = [{"artist": "missing unrelated artist", "title": "x"}]
        result = _ground_description(generated, catalog, prompt)
        self.assertIn("garage rock", result["description"].lower())
        self.assertIn("dilly dally", result["description"].lower())


if __name__ == "__main__":
    unittest.main()
