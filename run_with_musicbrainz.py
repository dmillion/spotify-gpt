#!/usr/bin/env python3
"""Tune Raider entrypoint with MusicBrainz enrichment enabled."""

from __future__ import annotations

import os

# Install enrichment hooks before run_app captures app-level functions.
import musicbrainz_integration  # noqa: F401,E402
import prompt_ideas_enrichment  # noqa: F401,E402
import run_app  # noqa: E402


if __name__ == "__main__":
    run_app.tone_raider.app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
