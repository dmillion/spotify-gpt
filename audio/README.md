# Local audio-library scanner

`scan_library.py` builds a local SQLite index from MP3 files without copying audio into the repository.

It reads ID3/MP3 metadata and, by default, uses `ffmpeg` to decode three short excerpts from each track (near the beginning, middle, and end). NumPy is then used to calculate lightweight audio features that can later support similarity search and playlist curation.

The default database is:

```text
data/audio_library.sqlite
```

The database is ignored by Git and should remain local.

## Features stored

- artist, album artist, title, album, genre, date, track number
- duration, bitrate, source sample rate, channels
- RMS loudness and peak level
- zero-crossing rate
- spectral centroid and 85% rolloff
- spectral flatness
- low / low-mid / mid / high energy ratios
- onset-density estimate
- approximate BPM

These are descriptive DSP features, not yet neural audio embeddings. Embeddings can be added later after validating that the lightweight index is useful.

## Requirements

Activate the repo virtual environment and install current dependencies:

```bash
source .venv/bin/activate
git pull
pip install -r requirements.txt
```

Full audio analysis also requires `ffmpeg` to be available in `PATH`:

```bash
ffmpeg -version
```

On a Mac with Homebrew, if needed:

```bash
brew install ffmpeg
```

## Find a mounted external drive

macOS normally mounts external drives under `/Volumes`:

```bash
ls /Volumes
```

## Recommended first test

Run only 25 MP3s first:

```bash
source .venv/bin/activate
git pull
pip install -r requirements.txt

python audio/scan_library.py "/Volumes/YOUR_DRIVE_OR_MUSIC_FOLDER" --limit 25
```

If the results look sensible, scan the whole library:

```bash
source .venv/bin/activate
git pull

python audio/scan_library.py "/Volumes/YOUR_DRIVE_OR_MUSIC_FOLDER"
```

The scanner is resumable. On later runs it skips files whose path, size, modification time, and feature-analysis version are unchanged.

To force a fresh analysis:

```bash
python audio/scan_library.py "/Volumes/YOUR_DRIVE_OR_MUSIC_FOLDER" --force
```

To inventory tags and technical MP3 metadata without decoding audio:

```bash
python audio/scan_library.py "/Volumes/YOUR_DRIVE_OR_MUSIC_FOLDER" --metadata-only
```

For a faster full-library first pass, shorter excerpts can be used:

```bash
python audio/scan_library.py "/Volumes/YOUR_DRIVE_OR_MUSIC_FOLDER" --sample-seconds 10
```

The default is three excerpts of up to 20 seconds each per track.
