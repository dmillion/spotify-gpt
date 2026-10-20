#!/usr/bin/env python3
"""Create consistent backups of Tune Raider SQLite databases while the app runs."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent


def backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # URI mode=ro prevents the backup command from creating absent databases.
    uri = source.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as original:
        with sqlite3.connect(str(destination), timeout=30) as target:
            original.backup(target, pages=100, sleep=0.1)
            status = target.execute("PRAGMA quick_check").fetchone()[0]
            if status != "ok":
                raise RuntimeError(f"Backup verification failed for {source}: {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backups")
    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = args.output_dir.expanduser().resolve() / timestamp
    databases = {
        "playlist_history.db": Path(os.environ.get("PLAYLIST_HISTORY_DB", ROOT / "data" / "playlist_history.db")),
        "audio_library.sqlite": Path(os.environ.get("AUDIO_LIBRARY_DB", ROOT / "data" / "audio_library.sqlite")),
    }
    copied = 0
    for label, configured in databases.items():
        source = configured.expanduser()
        if not source.is_absolute():
            source = ROOT / source
        if not source.is_file():
            print(f"SKIP {label}: source not found at {source}")
            continue
        target = folder / label
        try:
            backup_database(source, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        print(f"OK {source} -> {target} ({target.stat().st_size:,} bytes; quick_check=ok)")
        copied += 1
    if not copied:
        raise SystemExit("No SQLite databases found; no backup created.")
    print(f"Backup complete: {folder}")


if __name__ == "__main__":
    main()
