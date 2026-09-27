"""Load click-to-prompt support for saved playlist tracks."""
from __future__ import annotations

import run_app

tr = run_app.tone_raider
_original_home = tr.app.view_functions.get("home")


def _home_with_track_prompt_insert():
    html = _original_home() if _original_home else ""
    if isinstance(html, str) and "track_prompt_insert.js" not in html:
        html = html.replace(
            "</head>",
            '<script defer src="/static/track_prompt_insert.js"></script>\n</head>',
            1,
        )
    return html


if _original_home:
    tr.app.view_functions["home"] = _home_with_track_prompt_insert
