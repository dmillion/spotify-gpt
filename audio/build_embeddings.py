#!/usr/bin/env python3
"""Build learned music embeddings for indexed MP3s using MERT."""

from __future__ import annotations

import argparse
import datetime as dt
import math
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import numpy as np

DEFAULT_DB = Path("data/audio_library.sqlite")
DEFAULT_MODEL = "m-a-p/MERT-v1-95M"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_SAMPLE_SECONDS = 5.0
DEFAULT_POSITIONS = (0.15, 0.50, 0.85)
EMBEDDING_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS track_embeddings (
    path TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding_version INTEGER NOT NULL,
    dimensions INTEGER,
    excerpt_count INTEGER,
    analyzed_at TEXT NOT NULL,
    vector BLOB,
    error TEXT,
    PRIMARY KEY(path, model)
);
CREATE INDEX IF NOT EXISTS idx_track_embeddings_model ON track_embeddings(model);
"""

UPSERT = """
INSERT INTO track_embeddings (
    path, model, embedding_version, dimensions, excerpt_count,
    analyzed_at, vector, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(path, model) DO UPDATE SET
    embedding_version=excluded.embedding_version,
    dimensions=excluded.dimensions,
    excerpt_count=excluded.excerpt_count,
    analyzed_at=excluded.analyzed_at,
    vector=excluded.vector,
    error=excluded.error;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build learned MERT embeddings for successfully analyzed MP3s."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model ID")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N eligible tracks")
    parser.add_argument("--force", action="store_true", help="Rebuild embeddings even if already present")
    parser.add_argument("--sample-seconds", type=float, default=DEFAULT_SAMPLE_SECONDS)
    parser.add_argument(
        "--device",
        choices=("auto", "mps", "cpu"),
        default="auto",
        help="Inference device (default: auto; prefers Apple MPS when available)",
    )
    return parser.parse_args()


def choose_device(torch_module, requested: str) -> str:
    if requested == "cpu":
        return "cpu"
    if requested == "mps":
        if not torch_module.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is not available")
        return "mps"
    return "mps" if torch_module.backends.mps.is_available() else "cpu"


def resolve_ffmpeg() -> Optional[str]:
    """Prefer native Apple Silicon Homebrew ffmpeg over migrated Intel /usr/local tools."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        native = Path("/opt/homebrew/bin/ffmpeg")
        if native.is_file():
            return str(native)
    return shutil.which("ffmpeg")


def excerpt_starts(duration: float, excerpt_seconds: float) -> List[float]:
    if duration <= excerpt_seconds:
        return [0.0]
    max_start = max(0.0, duration - excerpt_seconds)
    starts = [max_start * p for p in DEFAULT_POSITIONS]
    output: List[float] = []
    for start in starts:
        if not output or abs(start - output[-1]) > 0.5:
            output.append(start)
    return output


def decode_excerpt(ffmpeg: str, path: str, start: float, seconds: float) -> np.ndarray:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{max(0.1, seconds):.3f}",
        "-i",
        path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(DEFAULT_SAMPLE_RATE),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "ffmpeg failed to decode excerpt")
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float32, copy=False)


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector.astype(np.float32, copy=False)
    return (vector / norm).astype(np.float32, copy=False)


def build_track_embedding(
    path: str,
    duration: float,
    ffmpeg: str,
    sample_seconds: float,
    feature_extractor,
    model,
    torch_module,
    device: str,
) -> np.ndarray:
    excerpt_vectors: List[np.ndarray] = []
    for start in excerpt_starts(duration, sample_seconds):
        remaining = max(0.1, duration - start) if duration else sample_seconds
        seconds = min(sample_seconds, remaining)
        samples = decode_excerpt(ffmpeg, path, start, seconds)
        if samples.size == 0:
            continue

        inputs = feature_extractor(
            samples,
            sampling_rate=DEFAULT_SAMPLE_RATE,
            return_tensors="pt",
            padding=False,
        )
        input_values = inputs["input_values"].to(device)
        attention_mask = inputs.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(device)

        with torch_module.inference_mode():
            outputs = model(input_values=input_values, attention_mask=attention_mask)
            hidden = outputs.last_hidden_state
            pooled = hidden.mean(dim=1).squeeze(0)
        excerpt_vectors.append(l2_normalize(pooled.detach().float().cpu().numpy()))

    if not excerpt_vectors:
        raise RuntimeError("no excerpts produced an embedding")

    return l2_normalize(np.mean(np.vstack(excerpt_vectors), axis=0))


def already_done(conn: sqlite3.Connection, path: str, model: str) -> bool:
    row = conn.execute(
        "SELECT embedding_version, vector, error FROM track_embeddings WHERE path = ? AND model = ?",
        (path, model),
    ).fetchone()
    return bool(row and int(row[0]) == EMBEDDING_VERSION and row[1] is not None and not row[2])


def main() -> int:
    args = parse_args()
    db_path = args.db.expanduser()
    if not db_path.exists():
        print(f"ERROR: database does not exist: {db_path}", file=sys.stderr)
        return 2

    ffmpeg = resolve_ffmpeg()
    if ffmpeg is None:
        print("ERROR: ffmpeg is required but was not found", file=sys.stderr)
        return 2

    print(f"Using ffmpeg: {ffmpeg}")

    # Fail early if ffmpeg itself is broken.
    probe = subprocess.run([ffmpeg, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if probe.returncode != 0:
        print(probe.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        return 2

    try:
        import torch
        from transformers import AutoModel, Wav2Vec2FeatureExtractor
    except ImportError:
        print(
            "ERROR: embedding dependencies are missing. Run: pip install -r requirements-audio-embeddings.txt",
            file=sys.stderr,
        )
        return 2

    try:
        device = choose_device(torch, args.device)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Loading {args.model} on {device}...")
    feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModel.from_pretrained(args.model, trust_remote_code=True).to(device).eval()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    rows = conn.execute(
        "SELECT path, COALESCE(duration_seconds, 0) FROM tracks WHERE error IS NULL ORDER BY path"
    ).fetchall()
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    eligible = len(rows)
    print(f"Eligible tracks: {eligible:,}")
    print(f"Embedding excerpts: up to 3 x {args.sample_seconds:.1f}s at {DEFAULT_SAMPLE_RATE} Hz")

    completed = 0
    skipped = 0
    failed = 0

    try:
        for index, (path, duration) in enumerate(rows, 1):
            if not args.force and already_done(conn, path, args.model):
                skipped += 1
                if index % 100 == 0 or index == eligible:
                    print(f"[{index}/{eligible}] unchanged embedding; skipping")
                continue

            error: Optional[str] = None
            vector: Optional[np.ndarray] = None
            try:
                vector = build_track_embedding(
                    path=path,
                    duration=float(duration or 0.0),
                    ffmpeg=ffmpeg,
                    sample_seconds=args.sample_seconds,
                    feature_extractor=feature_extractor,
                    model=model,
                    torch_module=torch,
                    device=device,
                )
            except Exception as exc:
                error = str(exc)[:1000]

            now = dt.datetime.now(dt.timezone.utc).isoformat()
            blob = vector.astype("<f4", copy=False).tobytes() if vector is not None else None
            dimensions = int(vector.size) if vector is not None else None
            excerpt_count = len(excerpt_starts(float(duration or 0.0), args.sample_seconds)) if vector is not None else None
            conn.execute(
                UPSERT,
                (
                    path,
                    args.model,
                    EMBEDDING_VERSION,
                    dimensions,
                    excerpt_count,
                    now,
                    blob,
                    error,
                ),
            )
            conn.commit()
            completed += 1
            if error:
                failed += 1
                print(f"[{index}/{eligible}] ERROR {Path(path).name}: {error}")
            else:
                print(f"[{index}/{eligible}] embedded {Path(path).name} [{dimensions} dims]")
    finally:
        conn.close()

    print(f"\nDone. embedded/updated={completed}, unchanged={skipped}, errors={failed}.")
    print(f"Local index: {db_path}")
    if failed and device == "mps":
        print("If failures mention MPS/Metal operations, retry those tracks with --device cpu.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
