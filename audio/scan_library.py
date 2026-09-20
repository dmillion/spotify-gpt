#!/usr/bin/env python3
"""Scan a local MP3 library and store metadata/audio features in SQLite.

The scanner never copies audio into the repository. It decodes short excerpts with
ffmpeg, computes lightweight DSP features with NumPy, and stores the results in a
local SQLite database for later similarity/playlist work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

FEATURE_VERSION = 1
DEFAULT_DB = Path("data/audio_library.sqlite")
DEFAULT_SAMPLE_RATE = 22050
DEFAULT_SAMPLE_SECONDS = 20.0
DEFAULT_EXCERPT_POSITIONS = (0.15, 0.50, 0.85)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    path TEXT PRIMARY KEY,
    file_size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    feature_version INTEGER NOT NULL,
    artist TEXT,
    album_artist TEXT,
    title TEXT,
    album TEXT,
    genre TEXT,
    date TEXT,
    track_number TEXT,
    duration_seconds REAL,
    bitrate_kbps REAL,
    source_sample_rate INTEGER,
    channels INTEGER,
    analyzed_at TEXT NOT NULL,
    analyzed_audio_seconds REAL,
    rms_dbfs REAL,
    peak_dbfs REAL,
    zero_crossing_rate REAL,
    spectral_centroid_hz REAL,
    spectral_rolloff_85_hz REAL,
    spectral_flatness REAL,
    low_energy_ratio REAL,
    low_mid_energy_ratio REAL,
    mid_energy_ratio REAL,
    high_energy_ratio REAL,
    onset_density REAL,
    tempo_bpm REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist_title ON tracks(artist, title);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_artist, album);
"""

UPSERT_SQL = """
INSERT INTO tracks (
    path, file_size, mtime_ns, feature_version,
    artist, album_artist, title, album, genre, date, track_number,
    duration_seconds, bitrate_kbps, source_sample_rate, channels,
    analyzed_at, analyzed_audio_seconds,
    rms_dbfs, peak_dbfs, zero_crossing_rate,
    spectral_centroid_hz, spectral_rolloff_85_hz, spectral_flatness,
    low_energy_ratio, low_mid_energy_ratio, mid_energy_ratio, high_energy_ratio,
    onset_density, tempo_bpm, error
) VALUES (
    :path, :file_size, :mtime_ns, :feature_version,
    :artist, :album_artist, :title, :album, :genre, :date, :track_number,
    :duration_seconds, :bitrate_kbps, :source_sample_rate, :channels,
    :analyzed_at, :analyzed_audio_seconds,
    :rms_dbfs, :peak_dbfs, :zero_crossing_rate,
    :spectral_centroid_hz, :spectral_rolloff_85_hz, :spectral_flatness,
    :low_energy_ratio, :low_mid_energy_ratio, :mid_energy_ratio, :high_energy_ratio,
    :onset_density, :tempo_bpm, :error
)
ON CONFLICT(path) DO UPDATE SET
    file_size=excluded.file_size,
    mtime_ns=excluded.mtime_ns,
    feature_version=excluded.feature_version,
    artist=excluded.artist,
    album_artist=excluded.album_artist,
    title=excluded.title,
    album=excluded.album,
    genre=excluded.genre,
    date=excluded.date,
    track_number=excluded.track_number,
    duration_seconds=excluded.duration_seconds,
    bitrate_kbps=excluded.bitrate_kbps,
    source_sample_rate=excluded.source_sample_rate,
    channels=excluded.channels,
    analyzed_at=excluded.analyzed_at,
    analyzed_audio_seconds=excluded.analyzed_audio_seconds,
    rms_dbfs=excluded.rms_dbfs,
    peak_dbfs=excluded.peak_dbfs,
    zero_crossing_rate=excluded.zero_crossing_rate,
    spectral_centroid_hz=excluded.spectral_centroid_hz,
    spectral_rolloff_85_hz=excluded.spectral_rolloff_85_hz,
    spectral_flatness=excluded.spectral_flatness,
    low_energy_ratio=excluded.low_energy_ratio,
    low_mid_energy_ratio=excluded.low_mid_energy_ratio,
    mid_energy_ratio=excluded.mid_energy_ratio,
    high_energy_ratio=excluded.high_energy_ratio,
    onset_density=excluded.onset_density,
    tempo_bpm=excluded.tempo_bpm,
    error=excluded.error;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recursively scan MP3s and build a local SQLite audio-feature index."
    )
    parser.add_argument("root", type=Path, help="Root folder/drive containing MP3 files")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="SQLite output path (default: data/audio_library.sqlite)",
    )
    parser.add_argument(
        "--sample-seconds",
        type=float,
        default=DEFAULT_SAMPLE_SECONDS,
        help="Seconds to decode at each of three positions per track (default: 20)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="Analysis sample rate (default: 22050 Hz)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Index tags/technical metadata without decoding audio",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-analyze files even when size/mtime/feature version are unchanged",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Analyze only the first N discovered MP3s (useful for a test run)",
    )
    return parser.parse_args()


def first_tag(tags: Optional[EasyID3], key: str) -> Optional[str]:
    if not tags:
        return None
    value = tags.get(key)
    if not value:
        return None
    text = str(value[0]).strip()
    return text or None


def read_metadata(path: Path) -> Dict[str, object]:
    audio = MP3(str(path), ID3=EasyID3)
    info = audio.info
    tags = audio.tags
    return {
        "artist": first_tag(tags, "artist"),
        "album_artist": first_tag(tags, "albumartist"),
        "title": first_tag(tags, "title") or path.stem,
        "album": first_tag(tags, "album"),
        "genre": first_tag(tags, "genre"),
        "date": first_tag(tags, "date"),
        "track_number": first_tag(tags, "tracknumber"),
        "duration_seconds": float(getattr(info, "length", 0.0) or 0.0),
        "bitrate_kbps": float(getattr(info, "bitrate", 0) or 0) / 1000.0,
        "source_sample_rate": int(getattr(info, "sample_rate", 0) or 0),
        "channels": int(getattr(info, "channels", 0) or 0),
    }


def decode_excerpt(
    ffmpeg: str,
    path: Path,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int,
) -> np.ndarray:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "{:.3f}".format(max(0.0, start_seconds)),
        "-t",
        "{:.3f}".format(max(0.1, duration_seconds)),
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "ffmpeg could not decode audio")
    if not result.stdout:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32)
    return samples / 32768.0


def excerpt_starts(duration: float, excerpt_seconds: float) -> List[float]:
    if duration <= excerpt_seconds:
        return [0.0]
    max_start = max(0.0, duration - excerpt_seconds)
    starts = [max_start * position for position in DEFAULT_EXCERPT_POSITIONS]
    deduped: List[float] = []
    for start in starts:
        if not deduped or abs(start - deduped[-1]) > 1.0:
            deduped.append(start)
    return deduped


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def frame_signal(samples: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
    if len(samples) < frame_size:
        samples = np.pad(samples, (0, frame_size - len(samples)))
    frame_count = 1 + max(0, (len(samples) - frame_size) // hop)
    shape = (frame_count, frame_size)
    strides = (samples.strides[0] * hop, samples.strides[0])
    return np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides)


def estimate_tempo(onset_envelope: np.ndarray, envelope_rate: float) -> Optional[float]:
    if len(onset_envelope) < 8 or not np.any(onset_envelope > 0):
        return None
    centered = onset_envelope - float(np.mean(onset_envelope))
    autocorr = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
    min_bpm, max_bpm = 60.0, 200.0
    min_lag = max(1, int(round(envelope_rate * 60.0 / max_bpm)))
    max_lag = min(len(autocorr) - 1, int(round(envelope_rate * 60.0 / min_bpm)))
    if max_lag <= min_lag:
        return None
    region = autocorr[min_lag : max_lag + 1]
    if not np.any(np.isfinite(region)):
        return None
    lag = min_lag + int(np.argmax(region))
    if lag <= 0:
        return None
    return float(60.0 * envelope_rate / lag)


def analyze_samples(samples: np.ndarray, sample_rate: int) -> Dict[str, Optional[float]]:
    if len(samples) == 0:
        raise RuntimeError("decoded excerpt contained no samples")

    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    peak = float(np.max(np.abs(samples)))
    signs = np.signbit(samples)
    zcr = float(np.mean(signs[1:] != signs[:-1])) if len(samples) > 1 else 0.0

    frame_size = 2048
    hop = 512
    frames = frame_signal(samples, frame_size, hop).copy()
    window = np.hanning(frame_size).astype(np.float32)
    spectra = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float64)
    power = np.square(spectra)
    freqs = np.fft.rfftfreq(frame_size, 1.0 / sample_rate)

    magnitude_sum = np.sum(spectra, axis=1) + 1e-12
    centroids = np.sum(spectra * freqs[None, :], axis=1) / magnitude_sum
    centroid = float(np.mean(centroids))

    cumulative = np.cumsum(power, axis=1)
    totals = cumulative[:, -1] + 1e-12
    targets = totals * 0.85
    rolloff_bins = np.argmax(cumulative >= targets[:, None], axis=1)
    rolloff = float(np.mean(freqs[rolloff_bins]))

    positive_spectra = spectra + 1e-12
    geometric = np.exp(np.mean(np.log(positive_spectra), axis=1))
    arithmetic = np.mean(positive_spectra, axis=1) + 1e-12
    flatness = float(np.mean(geometric / arithmetic))

    mean_power = np.mean(power, axis=0)
    total_power = float(np.sum(mean_power)) + 1e-12

    def band_ratio(low: float, high: float) -> float:
        mask = (freqs >= low) & (freqs < high)
        return float(np.sum(mean_power[mask]) / total_power)

    nyquist = sample_rate / 2.0
    low_ratio = band_ratio(20.0, 250.0)
    low_mid_ratio = band_ratio(250.0, 1000.0)
    mid_ratio = band_ratio(1000.0, min(4000.0, nyquist + 1.0))
    high_ratio = band_ratio(4000.0, nyquist + 1.0) if nyquist > 4000.0 else 0.0

    normalized = spectra / magnitude_sum[:, None]
    flux = np.sqrt(np.sum(np.square(np.maximum(0.0, normalized[1:] - normalized[:-1])), axis=1))
    if len(flux):
        threshold = float(np.median(flux) + 1.5 * np.std(flux))
        peaks = flux > threshold
        excerpt_seconds = len(samples) / float(sample_rate)
        onset_density = float(np.count_nonzero(peaks) / max(excerpt_seconds, 1e-6))
        tempo = estimate_tempo(flux, sample_rate / float(hop))
    else:
        onset_density = 0.0
        tempo = None

    return {
        "rms_dbfs": dbfs(rms),
        "peak_dbfs": dbfs(peak),
        "zero_crossing_rate": zcr,
        "spectral_centroid_hz": centroid,
        "spectral_rolloff_85_hz": rolloff,
        "spectral_flatness": flatness,
        "low_energy_ratio": low_ratio,
        "low_mid_energy_ratio": low_mid_ratio,
        "mid_energy_ratio": mid_ratio,
        "high_energy_ratio": high_ratio,
        "onset_density": onset_density,
        "tempo_bpm": tempo,
    }


def combine_features(feature_sets: Sequence[Dict[str, Optional[float]]]) -> Dict[str, Optional[float]]:
    if not feature_sets:
        return {}
    output: Dict[str, Optional[float]] = {}
    for key in feature_sets[0].keys():
        values = [row[key] for row in feature_sets if row.get(key) is not None]
        if not values:
            output[key] = None
        elif key == "tempo_bpm":
            output[key] = float(np.median(np.asarray(values, dtype=np.float64)))
        else:
            output[key] = float(np.mean(np.asarray(values, dtype=np.float64)))
    return output


def discover_mp3s(root: Path) -> List[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".mp3"),
        key=lambda path: str(path).casefold(),
    )


def unchanged(conn: sqlite3.Connection, path: Path, stat: object) -> bool:
    row = conn.execute(
        "SELECT file_size, mtime_ns, feature_version, error FROM tracks WHERE path = ?",
        (str(path.resolve()),),
    ).fetchone()
    if not row:
        return False
    return (
        int(row[0]) == int(getattr(stat, "st_size"))
        and int(row[1]) == int(getattr(stat, "st_mtime_ns"))
        and int(row[2]) == FEATURE_VERSION
        and not row[3]
    )


def base_record(path: Path, stat: object) -> Dict[str, object]:
    return {
        "path": str(path.resolve()),
        "file_size": int(getattr(stat, "st_size")),
        "mtime_ns": int(getattr(stat, "st_mtime_ns")),
        "feature_version": FEATURE_VERSION,
        "artist": None,
        "album_artist": None,
        "title": path.stem,
        "album": None,
        "genre": None,
        "date": None,
        "track_number": None,
        "duration_seconds": None,
        "bitrate_kbps": None,
        "source_sample_rate": None,
        "channels": None,
        "analyzed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "analyzed_audio_seconds": 0.0,
        "rms_dbfs": None,
        "peak_dbfs": None,
        "zero_crossing_rate": None,
        "spectral_centroid_hz": None,
        "spectral_rolloff_85_hz": None,
        "spectral_flatness": None,
        "low_energy_ratio": None,
        "low_mid_energy_ratio": None,
        "mid_energy_ratio": None,
        "high_energy_ratio": None,
        "onset_density": None,
        "tempo_bpm": None,
        "error": None,
    }


def scan_file(
    ffmpeg: Optional[str],
    path: Path,
    sample_seconds: float,
    sample_rate: int,
    metadata_only: bool,
) -> Dict[str, object]:
    stat = path.stat()
    record = base_record(path, stat)
    try:
        metadata = read_metadata(path)
        record.update(metadata)
        if metadata_only:
            return record
        if ffmpeg is None:
            raise RuntimeError("ffmpeg was not found in PATH")

        duration = float(record.get("duration_seconds") or 0.0)
        starts = excerpt_starts(duration, sample_seconds)
        features: List[Dict[str, Optional[float]]] = []
        decoded_seconds = 0.0
        for start in starts:
            remaining = max(0.1, duration - start) if duration else sample_seconds
            excerpt_length = min(sample_seconds, remaining)
            samples = decode_excerpt(ffmpeg, path, start, excerpt_length, sample_rate)
            if len(samples) == 0:
                continue
            decoded_seconds += len(samples) / float(sample_rate)
            features.append(analyze_samples(samples, sample_rate))
        if not features:
            raise RuntimeError("no audio excerpts could be decoded")
        record.update(combine_features(features))
        record["analyzed_audio_seconds"] = decoded_seconds
    except Exception as exc:  # keep scanning a large library even when one file is bad
        record["error"] = str(exc)[:1000]
    return record


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print("ERROR: scan root is not a directory: {}".format(root), file=sys.stderr)
        return 2
    if args.sample_seconds <= 0:
        print("ERROR: --sample-seconds must be greater than zero", file=sys.stderr)
        return 2
    if args.sample_rate < 8000:
        print("ERROR: --sample-rate must be at least 8000", file=sys.stderr)
        return 2

    ffmpeg = shutil.which("ffmpeg")
    if not args.metadata_only and ffmpeg is None:
        print(
            "ERROR: ffmpeg is required for audio analysis but was not found in PATH. "
            "Install ffmpeg or use --metadata-only.",
            file=sys.stderr,
        )
        return 2

    db_path = args.db.expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    files = discover_mp3s(root)
    if args.limit is not None:
        files = files[: max(0, args.limit)]

    print("Found {} MP3 files under {}".format(len(files), root))
    print("Database: {}".format(db_path))
    if not args.metadata_only:
        print(
            "Audio analysis: 3 x up to {:.0f}s excerpts per track at {} Hz".format(
                args.sample_seconds, args.sample_rate
            )
        )

    scanned = 0
    skipped = 0
    failed = 0

    try:
        for index, path in enumerate(files, 1):
            try:
                stat = path.stat()
            except OSError as exc:
                print("[{}/{}] ERROR {}: {}".format(index, len(files), path.name, exc))
                failed += 1
                continue

            if not args.force and unchanged(conn, path, stat):
                skipped += 1
                if index % 100 == 0 or index == len(files):
                    print("[{}/{}] unchanged; skipping {}".format(index, len(files), path.name))
                continue

            record = scan_file(
                ffmpeg=ffmpeg,
                path=path,
                sample_seconds=args.sample_seconds,
                sample_rate=args.sample_rate,
                metadata_only=args.metadata_only,
            )
            conn.execute(UPSERT_SQL, record)
            conn.commit()
            scanned += 1
            if record.get("error"):
                failed += 1
                print(
                    "[{}/{}] ERROR {}: {}".format(
                        index, len(files), path.name, record["error"]
                    )
                )
            else:
                artist = record.get("artist") or "Unknown Artist"
                title = record.get("title") or path.stem
                if args.metadata_only:
                    detail = "metadata"
                else:
                    detail = "{:.0f} BPM, {:.1f} dBFS RMS".format(
                        float(record.get("tempo_bpm") or 0.0),
                        float(record.get("rms_dbfs") or -120.0),
                    )
                print("[{}/{}] {} - {} [{}]".format(index, len(files), artist, title, detail))
    finally:
        conn.close()

    print(
        "\nDone. analyzed/updated={}, unchanged={}, errors={}.".format(
            scanned, skipped, failed
        )
    )
    print("Local index: {}".format(db_path))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
