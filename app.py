#!/usr/bin/env python3
"""Tune Raider application module."""

from app_bootstrap import *  # noqa: F401,F403


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
