#!/usr/bin/env python3
"""Experimental recording-level sonic knowledge probe. Does not alter playlists.

Run: python scripts/probe_sonic_knowledge.py
Optional: python scripts/probe_sonic_knowledge.py --output sonic_probe.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from scripts/ without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app

TRACKS = [
    ("King Gizzard & The Lizard Wizard", "Planet B"),
    ("King Gizzard & The Lizard Wizard", "Sense"),
    ("King Gizzard & The Lizard Wizard", "Work This Time"),
    ("King Gizzard & The Lizard Wizard", "Robot Stop"),
    ("King Gizzard & The Lizard Wizard", "Rattlesnake"),
    ("Frankie and the Witch Fingers", "Underneath You"),
    ("Frankie and the Witch Fingers", "Dracula Drug"),
    ("Thee Oh Sees", "I Come from the Mountain"),
    ("Thee Oh Sees", "The Dream"),
    ("Ty Segall", "Finger"),
    ("Fuzz", "What's in My Head?"),
    ("Psychedelic Porn Crumpets", "Cornflake"),
    ("Psychedelic Porn Crumpets", "Found God in a Tomato"),
    ("The Black Angels", "Bad Vibrations"),
    ("The Murlocs", "Space Cadet"),
    ("Levitation Room", "Headspace"),
    ("Acid Dad", "Mr. Major"),
    ("Damaged Bug", "Jet in Jungle"),
    ("Hooveriii", "See"),
    ("All Them Witches", "When God Comes Back"),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "tracks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "tempo": {"type": "string", "enum": ["slow", "medium", "fast", "unknown"]},
                    "aggression": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
                    "abrasiveness": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
                    "psychedelic": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
                    "basis": {"type": "string", "enum": ["recording_knowledge", "album_context", "artist_inference", "unknown"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "tempo", "aggression", "abrasiveness", "psychedelic",
                             "confidence", "basis", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tracks"],
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "Evaluate the SONIC CHARACTER of each specific recorded song, not the artist's general style. "
    "Do not assume every track by one artist sounds alike. No audio is supplied, so these are "
    "knowledge-based estimates, NOT measured audio features. Use recording_knowledge ONLY when "
    "you have specific knowledge of that exact song; album_context when relying on its album; "
    "artist_inference for artist/genre stereotypes; unknown otherwise. Do not fabricate listening "
    "experience, BPM, reviews, or specific production details. If uncertain, set confidence low "
    "or unknown, tempo unknown, and numeric values null. Tempo means perceived rhythmic speed, "
    "not intensity. Aggression is force/attack; abrasiveness is distortion/roughness; "
    "psychedelic is perceptual style. All numeric ratings are ordinal 0-5, not measurements. "
    "Return exactly one row for each input id and no other rows."
)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="sonic_probe.json")
    args = parser.parse_args()
    items = [{"id": index, "artist": artist, "title": title}
             for index, (artist, title) in enumerate(TRACKS, 1)]
    payload = app.model_json(INSTRUCTIONS, json.dumps({"tracks": items}),
                             SCHEMA, stage="sonic knowledge probe")
    rows = payload.get("tracks")
    if not isinstance(rows, list):
        raise ValueError("Model omitted tracks array")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise ValueError("Malformed model result")
        identifier = row["id"]
        if identifier in by_id or not 1 <= identifier <= len(items):
            raise ValueError(f"Unexpected or duplicate id: {identifier}")
        by_id[identifier] = row
    if len(by_id) != len(items):
        raise ValueError(f"Model returned {len(by_id)} of {len(items)} tracks")
    output = {
        "model": app.OLLAMA_MODEL,
        "purpose": "unverified recording-specific knowledge probe; not audio analysis",
        "results": [{**items[index - 1], **by_id[index]}
                    for index in range(1, len(items) + 1)],
    }
    path = Path(args.output)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(items)} estimates to {path}")
    print("ID | Tempo   | Agg | Abr | Psych | Confidence | Basis             | Track")
    for row in output["results"]:
        print(f"{row['id']:2} | {row['tempo']:<7} | {str(row['aggression']):>3} | "
              f"{str(row['abrasiveness']):>3} | {str(row['psychedelic']):>5} | "
              f"{row['confidence']:<10} | {row['basis']:<17} | "
              f"{row['artist']} - {row['title']}")


if __name__ == "__main__":
    run()
