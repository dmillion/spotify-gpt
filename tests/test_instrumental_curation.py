"""Regression: unknown instrumentals must reach recording-level verification."""
import unittest
from unittest.mock import patch

import run_app


class InstrumentalCurationTests(unittest.TestCase):
    def test_unknown_candidate_is_not_discarded_before_spotify_resolution(self):
        candidate = {"artist": "Example Band", "title": "Long Riff", "source": "local"}
        generated = {"name": "Instrumentals", "description": "Heavy psych", "tracks": [candidate]}
        with (
            patch.object(run_app, "_original_ask_for_hybrid_playlist", return_value=generated),
            patch.object(run_app, "apply_request_constraints", side_effect=lambda *args, **kwargs: args[1]),
            patch.object(run_app, "has_title_constraint", return_value=False),
            patch.object(run_app, "ensure_prompt_anchor", side_effect=lambda *args, **kwargs: args[1]),
            patch.object(run_app, "_broaden_sparse_general_result", side_effect=lambda *args, **kwargs: args[1]),
        ):
            result = run_app.ask_for_hybrid_playlist_with_safeguards(
                "Create instrumental stoner rock, absolutely no vocals"
            )
        self.assertEqual(result["tracks"], [candidate])
        self.assertNotIn("constraint_rejections", result)


if __name__ == "__main__":
    unittest.main()
