#!/usr/bin/env python3
"""Tune Raider application module.

Keep app and app_bootstrap as the same module object so runtime integrations patch
the namespace used by routes installed during bootstrap.
"""
from __future__ import annotations

import os
import sys

import app_bootstrap as _bootstrap

# Runtime integrations historically import app and replace functions such as
# ask_for_hybrid_playlist. The route closures installed by app_bootstrap resolve
# those functions from app_bootstrap's globals, so a star-import wrapper creates
# two independent namespaces and silently bypasses later patches. Alias this module
# to the bootstrap module instead.
sys.modules[__name__] = _bootstrap


if __name__ == "__main__":
    _bootstrap.app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=True,
    )
