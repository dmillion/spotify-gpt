#!/usr/bin/env python3
"""Find acoustically similar tracks in the local audio feature index."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

DEFAULT_DB = Path("data/audio_library.sqlite")
DEFAULT_MODEL = "m-a-p/MERT-v1-95M"

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
    parser = argparse.ArgumentParser(description="Rank indexed tracks by acoustic similarity.")
    parser.add_argument("query", nargs="?", help='Seed search text, e.g. "Weedeater Jason the Dragon"')
    parser.add_argument("--artist", help="Seed artist")
    parser.add_argument("--title", help="Seed title")
    parser.add_argument("--path", type=Path, help="Exact indexed MP3 path")
    parser.add_argument("--seed-id", type=int, help="Use a specific SQLite rowid")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--exclude-same-artist", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("auto", "embedding", "dsp"),
        default="auto",
        help="Similarity engine (default: auto; prefers embeddings when available)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model ID")
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
        for term in [t for t in normalize_text(args.query).split() if t]:
            like = f"%{term}%"
            conditions.append(
                "(LOWER(COALESCE(artist, '')) LIKE ? OR LOWER(COALESCE(title, '')) LIKE ? OR LOWER(COALESCE(album, '')) LIKE ?)"
            )
            params.extend([like, like, like])

    if len(conditions) == 1:
        raise ValueError("Provide a query, --artist/--title, --path, or --seed-id.")

    rows = conn.execute(
        "SELECT rowid AS id, * FROM tracks WHERE " + " AND ".join(conditions) +
        " ORDER BY artist, album, track_number, title LIMIT 50",
        params,
    ).fetchall()
    if not rows:
        # Helpful fallback: show nearby artist/title rows when one side matched.
        hints: List[sqlite3.Row] = []
        if args.artist:
            hints = conn.execute(
                "SELECT rowid AS id, * FROM tracks WHERE error IS NULL AND LOWER(COALESCE(artist,'')) LIKE ? ORDER BY album, track_number LIMIT ?",
                (f"%{normalize_text(args.artist)}%", max(1, args.candidates)),
            ).fetchall()
        if hints:
            print("No exact seed match. Nearby indexed tracks:")
            for row in hints:
                print(f"  {row['id']:>6}  {row_label(row)}")
            raise SystemExit(2)
        raise ValueError("No successfully analyzed indexed track matched the seed search.")

    if len(rows) == 1:
        return rows[0]
    if args.artist and args.title:
        exact = [
            row for row in rows
            if normalize_text(row["artist"]) == normalize_text(args.artist)
            and normalize_text(row["title"]) == normalize_text(args.title)
        ]
        if len(exact) == 1:
            return exact[0]

    print("Seed search matched multiple tracks. Re-run with --seed-id <id>:")
    for row in rows[: max(1, args.candidates)]:
        print(f"  {row['id']:>6}  {row_label(row)}")
    raise SystemExit(2)


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


def dsp_context(conn: sqlite3.Connection, seed: sqlite3.Row) -> Dict[str, List[Tuple[str, float]]]:
    columns = ", ".join(name for name, _ in FEATURES)
    rows = conn.execute(
        f"SELECT path, {columns} FROM tracks WHERE error IS NULL"
    ).fetchall()
    matrix = np.vstack([
        np.asarray([float(row[name]) if row[name] is not None else np.nan for name, _ in FEATURES])
        for row in rows
    ])
    medians = np.nanmedian(matrix, axis=0)
    q1 = np.nanpercentile(matrix, 25, axis=0)
    q3 = np.nanpercentile(matrix, 75, axis=0)
    scales = q3 - q1
    std = np.nanstd(matrix, axis=0)
    scales = np.where(scales > 1e-12, scales, std)
    scales = np.where(scales > 1e-12, scales, 1.0)
    weights = np.sqrt(np.asarray([weight for _, weight in FEATURES]))

    seed_vec = np.asarray([float(seed[name]) if seed[name] is not None else np.nan for name, _ in FEATURES])
    seed_z = (np.where(np.isnan(seed_vec), medians, seed_vec) - medians) / scales
    output: Dict[str, List[Tuple[str, float]]] = {}
    for idx, row in enumerate(rows):
        vec = np.where(np.isnan(matrix[idx]), medians, matrix[idx])
        z = (vec - medians) / scales
        diff = np.abs((z - seed_z) * weights)
        pairs = [(FEATURES[i][0], float(diff[i])) for i in range(len(FEATURES))]
        pairs.sort(key=lambda x: x[1])
        output[row["path"]] = pairs[:3]
    return output


def load_dsp_results(conn: sqlite3.Connection, seed: sqlite3.Row, exclude_same_artist: bool) -> List[Tuple[float, sqlite3.Row]]:
    columns = ", ".join(name for name, _ in FEATURES)
    rows = conn.execute(
        f"SELECT rowid AS id, path, artist, title, album, {columns} FROM tracks WHERE error IS NULL"
    ).fetchall()
    matrix = np.vstack([
        np.asarray([float(row[name]) if row[name] is not None else np.nan for name, _ in FEATURES])
        for row in rows
    ])
    medians = np.nanmedian(matrix, axis=0)
    q1 = np.nanpercentile(matrix, 25, axis=0)
    q3 = np.nanpercentile(matrix, 75, axis=0)
    scales = q3 - q1
    std = np.nanstd(matrix, axis=0)
    scales = np.where(scales > 1e-12, scales, std)
    scales = np.where(scales > 1e-12, scales, 1.0)
    weights = np.sqrt(np.asarray([weight for _, weight in FEATURES]))
    filled = np.where(np.isnan(matrix), medians[None, :], matrix)
    z = (filled - medians[None, :]) / scales
    seed_vec = np.asarray([float(seed[name]) if seed[name] is not None else np.nan for name, _ in FEATURES])
    seed_z = (np.where(np.isnan(seed_vec), medians, seed_vec) - medians) / scales
    seed_artist = normalize_text(seed["artist"])

    results: List[Tuple[float, sqlite3.Row]] = []
    for i, row in enumerate(rows):
        if row["id"] == seed["id"]:
            continue
        if exclude_same_artist and seed_artist and normalize_text(row["artist"]) == seed_artist:
            continue
        distance = float(np.sqrt(np.mean(np.square((z[i] - seed_z) * weights))))
        results.append((100.0 / (1.0 + distance), row))
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def embedding_available(conn: sqlite3.Connection, seed_path: str, model: str) -> bool:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM track_embeddings WHERE model = ? AND vector IS NOT NULL AND error IS NULL",
            (model,),
        ).fetchone()
        seed = conn.execute(
            "SELECT 1 FROM track_embeddings WHERE path = ? AND model = ? AND vector IS NOT NULL AND error IS NULL",
            (seed_path, model),
        ).fetchone()
        return bool(row and row[0] > 1 and seed)
    except sqlite3.OperationalError:
        return False


def load_embedding_results(conn: sqlite3.Connection, seed: sqlite3.Row, model: str, exclude_same_artist: bool) -> List[Tuple[float, sqlite3.Row]]:
    seed_row = conn.execute(
        "SELECT vector, dimensions FROM track_embeddings WHERE path = ? AND model = ? AND vector IS NOT NULL AND error IS NULL",
        (seed["path"], model),
    ).fetchone()
    if not seed_row:
        raise ValueError("Seed track does not have an embedding yet.")
    seed_vec = np.frombuffer(seed_row[0], dtype="<f4")
    seed_norm = float(np.linalg.norm(seed_vec)) or 1.0

    rows = conn.execute(
        """
        SELECT t.rowid AS id, t.path, t.artist, t.title, t.album, e.vector, e.dimensions
        FROM track_embeddings e
        JOIN tracks t ON t.path = e.path
        WHERE e.model = ? AND e.vector IS NOT NULL AND e.error IS NULL AND t.error IS NULL
        """,
        (model,),
    ).fetchall()
    seed_artist = normalize_text(seed["artist"])
    results: List[Tuple[float, sqlite3.Row]] = []
    for row in rows:
        if row["id"] == seed["id"]:
            continue
        if exclude_same_artist and seed_artist and normalize_text(row["artist"]) == seed_artist:
            continue
        vec = np.frombuffer(row["vector"], dtype="<f4")
        if vec.size != seed_vec.size:
            continue
        denom = seed_norm * (float(np.linalg.norm(vec)) or 1.0)
        cosine = float(np.dot(seed_vec, vec) / denom)
        results.append((max(0.0, min(100.0, cosine * 100.0)), row))
    results.sort(key=lambda x: x[0], reverse=True)
    return results


def dedupe(results: Sequence[Tuple[float, sqlite3.Row]], seed: sqlite3.Row) -> List[Tuple[float, sqlite3.Row]]:
    seen = {(normalize_text(seed["artist"]), normalize_text(seed["title"]))}
    output: List[Tuple[float, sqlite3.Row]] = []
    for score, row in results:
        key = (normalize_text(row["artist"]), normalize_text(row["title"]))
        if key in seen:
            continue
        seen.add(key)
        output.append((score, row))
    return output


def main() -> int:
    args = parse_args()
    if not args.db.expanduser().exists():
        print(f"ERROR: database does not exist: {args.db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(str(args.db.expanduser()))
    conn.row_factory = sqlite3.Row
    try:
        seed = find_seed(conn, args)
        mode = args.mode
        if mode == "auto":
            mode = "embedding" if embedding_available(conn, seed["path"], args.model) else "dsp"
        if mode == "embedding" and not embedding_available(conn, seed["path"], args.model):
            raise ValueError("Embedding mode requested, but this seed/model is not embedded yet. Run audio/build_embeddings.py first.")

        if mode == "embedding":
            results = load_embedding_results(conn, seed, args.model, args.exclude_same_artist)
        else:
            results = load_dsp_results(conn, seed, args.exclude_same_artist)
        results = dedupe(results, seed)
        context = dsp_context(conn, seed)

        print(f"Seed: {row_label(seed)}")
        print(f"Similarity engine: {mode}" + (f" ({args.model})" if mode == "embedding" else ""))
        print("Scores are relative similarity values, not probabilities.\n")
        for rank, (score, row) in enumerate(results[: max(1, args.limit)], 1):
            reason = format_reason(context.get(row["path"], []))
            print(f"{rank:>2}. {score:5.1f}  {row_label(row)}")
            if reason:
                print(f"    DSP context: {reason}")
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
