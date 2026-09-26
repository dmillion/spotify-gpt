#!/usr/bin/env python3
"""Tune Raider entrypoint with MusicBrainz enrichment enabled."""

# Install MusicBrainz hooks before run_app captures app-level functions.
import musicbrainz_integration  # noqa: F401
import run_app  # noqa: F401,E402
