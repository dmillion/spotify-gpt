"""Load saved-playlist @ mention support on the Tune Raider prompt UI."""
from __future__ import annotations

import run_app

tr = run_app.tone_raider
_original_home = tr.app.view_functions.get("home")


def _home_with_playlist_mentions():
    html = _original_home() if _original_home else ""
    if isinstance(html, str) and "prompt_playlist_mentions.js" not in html:
        html = html.replace(
            "</head>",
            '<script defer src="/static/prompt_playlist_mentions.js"></script>\n</head>',
            1,
        )
    return html


if _original_home:
    tr.app.view_functions["home"] = _home_with_playlist_mentions
