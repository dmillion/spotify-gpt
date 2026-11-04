"""Bounded, evidence-aware scoring of external discovery candidates.

Track tags are weak user-supplied evidence, not measured BPM or audio features.
Only the highest-ranked candidates are queried to bound network cost.
"""
from __future__ import annotations

import re

import sonic_ranking
from discovery_novelty import norm

NEGATIVE = {
    "speed": {"slow", "slowcore", "downtempo", "chill", "relaxing", "mellow", "ambient"},
    "drive": {"ambient", "chill", "relaxing", "mellow", "ballad"},
    "abrasion": {"soft rock", "acoustic", "ambient", "mellow", "dream pop"},
}
# This is a tag-level proxy, not an audio measurement.
def adjustment(prompt, artist, title):
    active = sonic_ranking.intent(prompt)
    if not any(active.values()):
        return 0.0, {}
    tags = set(sonic_ranking.track_tags(artist, title))
    if not tags:
        return 0.0, {"status": "no_track_tags"}
    hits, conflicts = {}, {}
    for dimension in ("speed", "drive", "abrasion", "psych", "genre"):
        if not active[dimension]:
            continue
        positive = sorted(tags & {norm(t) for t in sonic_ranking.SIGNALS[dimension]})
        negative = sorted(tags & NEGATIVE.get(dimension, set()))
        if positive:
            hits[dimension] = positive
        if negative:
            conflicts[dimension] = negative
    # Bounded adjustment: evidence can meaningfully distinguish two tracks
    # by the same artist without overruling all other discovery signals.
    bonus = sum({"speed": 13, "drive": 9, "abrasion": 12,
                 "psych": 5, "genre": 3}[key] for key in hits)
    penalty = sum({"speed": 15, "drive": 9, "abrasion": 10}[key]
                  for key in conflicts)
    return float(min(30, bonus) - min(25, penalty)), {"status": "matched" if hits or conflicts else "unrelated_tags", "positive": hits, "conflicts": conflicts}
