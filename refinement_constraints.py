"""Deterministic refinement constraints independent of model-proposed indexes."""
from __future__ import annotations

import re


def normalized(value):
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def excluded_artists(instruction, tracks):
    """Find named artists in explicit removal clauses, including comma lists."""
    text = str(instruction or "")
    clauses = re.split(r"[.;\n]", text)
    removed = set()
    for clause in clauses:
        match = re.search(r"\b(?:remove|exclude|drop|delete|without|no more|get rid of)\b(.+)", clause, re.I)
        if not match:
            continue
        scope = re.split(r"\b(?:find|replace|add|include|keep|instead|more like)\b", match.group(1), maxsplit=1, flags=re.I)[0]
        clean_scope = normalized(scope)
        for track in tracks:
            artist = normalized(track.get("artist"))
            if artist and re.search(r"(?<!\w)" + re.escape(artist) + r"(?!\w)", clean_scope):
                removed.add(artist)
    return removed


def filter_removed(instruction, current, additions=(), model_indexes=()):
    blocked = excluded_artists(instruction, current)
    indexes = {int(i) for i in model_indexes if type(i) is int}
    retained, removed = [], []
    for i, track in enumerate(current, 1):
        if i in indexes or normalized(track.get("artist")) in blocked:
            removed.append(track)
        else:
            retained.append(track)
    filtered_additions = [t for t in additions if normalized(t.get("artist")) not in blocked]
    return retained, filtered_additions, removed, blocked
