"""Conservative checks after LLM curation for explicitly specified sound features."""
from __future__ import annotations

from musical_similarity import emphasis


def filter_selection(prompt, selected, ranked_candidates, *, min_measured_fit=58):
    """Reject demonstrably poor measured matches; do not invent external features.

    For unmeasured recordings, no numeric filter is possible. Keep those
    candidates but expose how many were accepted without acoustic evidence.
    """
    active = emphasis(prompt)
    if not active:
        return selected, []
    indexed = {(str(c.get("artist") or "").casefold(),
                str(c.get("title") or "").casefold()): c for c in ranked_candidates}
    kept, rejected = [], []
    for row in selected:
        key = (str(row.get("artist") or "").casefold(),
               str(row.get("title") or "").casefold())
        candidate = indexed.get(key) or {}
        fit = candidate.get("musical_fit")
        if fit is not None and fit < min_measured_fit:
            rejected.append(f"{row.get('artist')} - {row.get('title')} (measured sound fit {fit})")
        else:
            kept.append(row)
    return kept, rejected
