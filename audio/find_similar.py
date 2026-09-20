#!/usr/bin/env python3
"""Find acoustically similar tracks in the local audio feature index."""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

DEFAULT_DB = Path("data/audio_library.sqlite")

# Weight the features that most directly describe heaviness/groove/timbre a little more.
FEATURES: Sequence[Tuple[str, float]] = (
    ("tempo_bpm", 1.15),
    ("rms_dbfs", 0.80),
    ("zero_crossing_rate", 0.80),
    ("spectral_centroid_hz", 1.05),
    ("spectral_rolloff_85_hz", 0.80),
    ("spectral_flatness", 1.15),
    ("low_energy_ratio", 1.20),
    ("low_mid_energy_ratio", 1.10),
    ("mid_energy_ratio", 0.90),
    ("high_energy_ratio", 0.75),
    ("onset_density", 1.15),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank tracks in the local MP3 index by acoustic similarity."
    )
    parser.add_argument(
        "query",
        nargs="?",
        help='Seed search text, e.g. "Weedeater God Luck and Good Speed"',
    )
    parser.add_argument("--artist", help="Seed artist (combine with --title for an exact search)")
    parser.add_argument("--title", help="Seed track title")
    parser.add_argument("--path", type=Path, help="Use an exact indexed MP3 path as the seed")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--limit", type=int, default=25, help="Number of matches to show (default: 25)")
    parser.add_argument(
        "--exclude-same-artist",
        action="store_true",
        help="Do not return other tracks by the seed artist",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=8,
        help="If the seed search is ambiguous, show this many choices (default: 8)",
    )
    parser.add_argument(
        "--seed-id",
        type=int,
        help="Use a specific rowid from a previous ambiguous-search result",
    )
    return parser.parse_args()


def normalize_text(value: Optional[str]) -> str:
    return (value or "").casefold().strip()


def row_label(row: sqlite3.Row) -> str:
    artist = row["artist"] or "Unknown Artist"
    title = row["title"] or Path(row["path"]).stem
    album = row["album"] or "Unknown Album"
    return f"{artist} - {title} [{album}]"


def find_seed(conn: sqlite3.Connection, args: argparse.Namespace) -> sqlite3.Row:
    if args.seed_id is not None:
        row = conn.execute(
            "SELECT rowid AS id, * FROM tracks WHERE rowid = ? AND error IS NULL",
            (args.seed_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"No successfully analyzed track with rowid {args.seed_id}.")
        return row

    if args.path:
        path = str(args.path.expanduser().resolve())
        row = conn.execute(
            "SELECT rowid AS id, * FROM tracks WHERE path = ? AND error IS NULL",
            (path,),
        ).fetchone()
        if not row:
            raise ValueError(f"No successfully analyzed indexed track at: {path}")
        return row

    conditions = ["error IS NULL"]
    params: List[object] = []

    if args.artist:
        conditions.append("LOWER(COALESCE(artist, '')) LIKE ?")
        params.append(f"%{normalize_text(args.artist)}%")
    if args.title:
        conditions.append("LOWER(COALESCE(title, '')) LIKE ?")
        params.append(f"%{normalize_text(args.title)}%")

    if args.query:
        terms = [term for term in normalize_text(args.query).split() if term]
        for term in terms:
            conditions.append(
                "(LOWER(COALESCE(artist, '')) LIKE ? OR LOWER(COALESCE(title, '')) LIKE ? OR LOWER(COALESCE(album, '')) LIKE ?)"
            )
            like = f"%{term}%"
            params.extend([like, like, like])

    if len(conditions) == 1:
        raise ValueError("Provide a query, --artist/--title, --path, or --seed-id.")

    rows = conn.execute(
        "SELECT rowid AS id, * FROM tracks WHERE " + " AND ".join(conditions) + " ORDER BY artist, album, track_number, title LIMIT 50",
        params,
    ).fetchall()

    if not rows:
        raise ValueError("No successfully analyzed indexed track matched the seed search.")
    if len(rows) == 1:
        return rows[0]

    # Prefer a single exact artist/title match when both were supplied.
    if args.artist and args.title:
        exact = [
            row
            for row in rows
            if normalize_text(row["artist"]) == normalize_text(args.artist)
            and normalize_text(row["title"]) == normalize_text(args.title)
        ]
        if len(exact) == 1:
            return exact[0]

    print("Seed search matched multiple tracks. Re-run with --seed-id <id>:")
    for row in rows[: max(1, args.candidates)]:
        print(f"  {row['id']:>6}  {row_label(row)}")
    raise SystemExit(2)


def load_feature_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    columns = ", ".join(name for name, _ in FEATURES)
    return conn.execute(
        f"SELECT rowid AS id, path, artist, title, album, {columns} FROM tracks WHERE error IS NULL"
    ).fetchall()


def robust_center_scale(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    medians = np.nanmedian(matrix, axis=0)
    q1 = np.nanpercentile(matrix, 25.0, axis=0)
    q3 = np.nanpercentile(matrix, 75.0, axis=0)
    scales = q3 - q1

    # Fall back to standard deviation for columns with a nearly zero IQR.
    std = np.nanstd(matrix, axis=0)
    scales = np.where(scales > 1e-12, scales, std)
    scales = np.where(scales > 1e-12, scales, 1.0)
    return medians, scales


def feature_vector(row: sqlite3.Row) -> np.ndarray:
    return np.asarray(
        [float(row[name]) if row[name] is not None else np.nan for name, _ in FEATURES],
        dtype=np.float64,
    )


def similarity_rows(rows: List[sqlite3.Row], seed: sqlite3.Row, exclude_same_artist: bool) -> List[Tuple[float, sqlite3.Row, List[Tuple[str, float]]]]:
    matrix = np.vstack([feature_vector(row) for row in rows])
    medians, scales = robust_center_scale(matrix)
    weights = np.sqrt(np.asarray([weight for _, weight in FEATURES], dtype=np.float64))

    # Missing values are imputed to the library median, which makes that feature neutral.
    filled = np.where(np.isnan(matrix), medians[None, :], matrix)
    z = (filled - medians[None, :]) / scales[None, :]

    seed_vec = feature_vector(seed)
    seed_filled = np.where(np.isnan(seed_vec), medians, seed_vec)
    seed_z = (seed_filled - medians) / scales

    results: List[Tuple[float, sqlite3.Row, List[Tuple[str, float]]]] = []
    seed_artist = normalize_text(seed["artist"])

    for index, row in enumerate(rows):
        if row["id"] == seed["id"]:
            continue
        if exclude_same_artist and seed_artist and normalize_text(row["artist"]) == seed_artist:
            continue

        diff = (z[index] - seed_z) * weights
        distance = float(np.sqrt(np.mean(np.square(diff))))
        # Map distance to a simple 0..100 score. This is relative similarity, not a probability.
        score = 100.0 / (1.0 + distance)

        contributions = []
        for feature_index, (name, _) in enumerate(FEATURES):
            contributions.append((name, abs(float(diff[feature_index]))))
        contributions.sort(key=lambda item: item[1])
        results.append((score, row, contributions[:3]))

    results.sort(key=lambda item: item[0], reverse=True)
    return results


def format_reason(contributions: Sequence[Tuple[str, float]]) -> str:
    labels: Dict[str, str] = {
        "tempo_bpm": "tempo",
        "rms_dbfs": "loudness",
        "zero_crossing_rate": "texture",
        "spectral_centroid_hz": "brightness",
        "spectral_rolloff_85_hz": "upper spectrum",
        "spectral_flatness": "fuzz/noise texture",
        "low_energy_ratio": "bass weight",
        "low_mid_energy_ratio": "low-mid weight",
        "mid_energy_ratio": "midrange weight",
        "high_energy_ratio": "high-frequency weight",
        "onset_density": "rhythmic density",
    }
    return ", ".join(labels.get(name, name) for name, _ in contributions)


def main() -> int:
    args = parse_args()
    db_path = args.db.expanduser()
    if not db_path.exists():
        print(f"ERROR: database does not exist: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        seed = find_seed(conn, args)
        rows = load_feature_rows(conn)
        if not rows:
            print("ERROR: no successfully analyzed tracks found in database", file=sys.stderr)
            return 2

        results = similarity_rows(rows, seed, args.exclude_same_artist)
        print(f"Seed: {row_label(seed)}")
        print(f"Indexed comparison pool: {len(rows):,} successfully analyzed tracks")
        print("Similarity score is relative acoustic distance, not a probability.\n")

        for rank, (score, row, reasons) in enumerate(results[: max(1, args.limit)], 1):
            print(
                f"{rank:>2}. {score:5.1f}  {row_label(row)}\n"
                f"    closest on: {format_reason(reasons)}"
            )
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
