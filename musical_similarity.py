"""Prompt-aware musical-fit ranking for Tune Raider candidate pools.

Only local analyzed tracks have measured audio features. External metadata
does not support claims about tempo, guitar intensity or structural progression.
"""
from __future__ import annotations

import math
import re

AXES = ("tempo", "rhythmic_density", "loudness", "low_mid_weight", "bass_weight",
        "noise_texture", "brightness")

def emphasis(prompt):
    words = str(prompt or "").casefold()
    flags = {
        "tempo": bool(re.search(r"\b(upbeat|uptempo|fast|brisk|energetic|high.energy|quick|speedy)\b", words)),
        "rhythmic_density": bool(re.search(r"\b(driving|pulsing|propulsive|rhythmic|groov(?:e|y|ing)|relentless|momentum)\b", words)),
        "loudness": bool(re.search(r"\b(heavy|loud|intense|fierce|powerful|crushing|aggressive|guitar.intensity|riff)\b", words)),
        "low_mid_weight": bool(re.search(r"\b(guitar|riff|fuzz|distort(?:ed|ion)|crunch|heavy)\b", words)),
        "noise_texture": bool(re.search(r"\b(fuzz|distort(?:ed|ion)|gritty|noisy|garage|raw)\b", words)),
        "progression": bool(re.search(r"\b(progression|progressive|evolving|build(?:ing|s)?|crescendo|dynamic|develop(?:ment|ing)?)\b", words)),
    }
    return {axis: active for axis, active in flags.items() if active}


def _clamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, value)) if math.isfinite(value) else None


def acoustic_fit(candidate, targets, prompt):
    """Measured-fit score in [0,100], or None when no comparable audio data.

    Progression cannot be inferred from static summary features; no invented
    progression measurements are created.
    """
    sound = candidate.get("sound_percentiles") or candidate.get("sound") or {}
    if not isinstance(sound, dict):
        return None
    active = emphasis(prompt)
    weights = {
        "tempo": 3.0 if active.get("tempo") else 1.0,
        "rhythmic_density": 3.2 if active.get("rhythmic_density") else 1.0,
        "loudness": 2.5 if active.get("loudness") else 1.0,
        "low_mid_weight": 2.8 if active.get("low_mid_weight") else 1.0,
        "noise_texture": 2.0 if active.get("noise_texture") else 1.0,
        "bass_weight": 1.0,
        "brightness": 1.0,
    }
    total = 0.0
    weight_sum = 0.0
    for axis, target in targets.items():
        if axis not in AXES:
            continue
        target, observed = _clamp(target), _clamp(sound.get(axis))
        if target is None or observed is None:
            continue
        weight = weights[axis]
        total += weight * (100.0 - abs(target - observed))
        weight_sum += weight
    return round(total / weight_sum, 2) if weight_sum else None


def score(candidate, plan, prompt):
    """Metadata score plus acoustic similarity when actually measured."""
    artist = str(candidate.get("artist") or "").casefold()
    text = " ".join(str(candidate.get(k) or "") for k in
                    ("title", "artist", "album", "genre", "relationship")).casefold()
    seeds = {str(a).casefold() for a in plan.get("artists", [])}
    terms = [str(t).casefold() for t in plan.get("terms", []) if str(t).strip()]
    metadata = min(30.0, (9 if artist in seeds else 0) +
                   min(12, 4 * sum(term in text for term in terms)) +
                   4 * float(candidate.get("match") or 0))
    fit = acoustic_fit(candidate, plan.get("sound") or {}, prompt)
    if fit is None:
        # Neutral acoustic uncertainty: never pretend Last.fm/Spotify artist
        # similarity proves a track's sound measurements.
        return round(40.0 + metadata, 2), None
    return round(0.75 * fit + 0.25 * metadata, 2), fit


def rank(candidates, plan, prompt):
    ranked = []
    for index, candidate in enumerate(candidates):
        value, fit = score(candidate, plan, prompt)
        ranked.append((value, index, {**candidate, "musical_fit": fit,
                                     "relevance_score": value}))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]
