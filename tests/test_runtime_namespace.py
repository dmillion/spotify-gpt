import unittest

import app
import app_bootstrap
from anchor_policy import _prompt_artist_name


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


if __name__ == "__main__":
    unittest.main()
