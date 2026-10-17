#!/usr/bin/env python3
"""Analyze an authorized audio file or live input in bounded PCM chunks.

This intentionally does not automate or capture playback from streaming services.
Features are stored separately from the existing local MP3 library catalog.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np

from scan_library import analyze_samples, combine_features

SCHEMA = """
CREATE TABLE IF NOT EXISTS listening_analyses (
    id TEXT PRIMARY KEY,
    source_label TEXT NOT NULL,
    started_at TEXT NOT NULL,
    sample_rate INTEGER NOT NULL,
    analyzed_seconds REAL NOT NULL,
    chunk_seconds REAL NOT NULL,
    feature_version INTEGER NOT NULL,
    features_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listening_source ON listening_analyses(source_label);
"""
FEATURE_VERSION = 1


def arguments():
    parser = argparse.ArgumentParser(description="Analyze authorized audio without keeping a recording.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="Locally accessible, authorized audio file")
    group.add_argument("--device", help="FFmpeg AVFoundation audio device index on macOS, e.g. 0")
    parser.add_argument("--label", required=True, help="Recording/track identifier assigned by operator")
    parser.add_argument("--db", type=Path, default=Path("data/audio_library.sqlite"))
    parser.add_argument("--seconds", type=float, default=60.0, help="Maximum listening duration")
    parser.add_argument("--chunk-seconds", type=float, default=10.0)
    parser.add_argument("--sample-rate", type=int, default=22050)
    return parser.parse_args()


def make_command(args, ffmpeg):
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if args.file:
        if not args.file.is_file():
            raise ValueError("Input file does not exist")
        cmd += ["-i", str(args.file)]
    else:
        if sys.platform != "darwin":
            raise ValueError("Live AVFoundation device capture requires macOS")
        if not args.device.isdigit():
            raise ValueError("Device must be a numeric AVFoundation audio device index")
        cmd += ["-f", "avfoundation", "-i", ":" + args.device]
    cmd += [
        "-vn", "-ac", "1", "-ar", str(args.sample_rate),
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    return cmd


def run():
    args = arguments()
    if args.seconds <= 0 or args.chunk_seconds <= 0 or args.sample_rate < 8000:
        raise ValueError("Seconds and chunk-seconds must be positive; sample-rate must be >= 8000")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required and was not found in PATH")
    chunk_samples = max(2048, round(args.chunk_seconds * args.sample_rate))
    maximum_samples = round(args.seconds * args.sample_rate)
    command = make_command(args, ffmpeg)
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.stdout is None:
        raise RuntimeError("ffmpeg produced no stdout")
    features = []
    consumed = 0
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        while consumed < maximum_samples:
            target = min(chunk_samples, maximum_samples - consumed)
            raw = bytearray()
            wanted = target * 4
            while len(raw) < wanted:
                next_bytes = proc.stdout.read(wanted - len(raw))
                if not next_bytes:
                    break
                raw.extend(next_bytes)
            if not raw:
                break
            usable = len(raw) - (len(raw) % 4)
            samples = np.frombuffer(raw[:usable], dtype="<f4")
            if not len(samples):
                break
            features.append(analyze_samples(samples, args.sample_rate))
            consumed += len(samples)
            print(f"Analyzed {consumed / args.sample_rate:.1f}s", flush=True)
            if len(raw) < wanted:
                break
    finally:
        proc.terminate() if proc.poll() is None else None
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    if not features:
        raise RuntimeError("No decoded audio was received; check the file or device")
    combined = combine_features(features)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO listening_analyses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), args.label, started, args.sample_rate,
                consumed / args.sample_rate, args.chunk_seconds,
                FEATURE_VERSION, json.dumps(combined, allow_nan=False),
            ),
        )
    print(json.dumps({
        "label": args.label, "analyzed_seconds": consumed / args.sample_rate,
        "features": combined
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
