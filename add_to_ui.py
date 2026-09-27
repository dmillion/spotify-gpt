"""Load the Add-to control on the Tune Raider history UI."""
from __future__ import annotations

import run_app

tr = run_app.tone_raider
_original_home = tr.app.view_functions.get("home")


def _home_with_add_to():
    html = _original_home() if _original_home else ""
    if isinstance(html, str) and "add_to_controls.js" not in html:
        html = html.replace(
            "</head>",
            '<script defer src="/static/add_to_controls.js"></script>\n</head>',
            1,
        )
    return html


if _original_home:
    tr.app.view_functions["home"] = _home_with_add_to
