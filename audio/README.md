# Local audio-library scanner

`scan_library.py` builds a local SQLite index from MP3 files without copying audio into the repository.

Use the newer MacBook Pro for audio indexing and other heavy local compute. The older iMac is intended for prompting and lightweight commands only.

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

On the MacBook Pro with Homebrew, if needed:

```bash
brew install ffmpeg
```

## Current WD Passport music roots

The current MP3 library is spread across these two roots:

```text
/Volumes/WD Passport/Old MacBook Stuff/iTunes Music
/Volumes/WD Passport/Music
```

The scanner is recursive, so nested artist/album folders under each root are included automatically.

Both roots can be scanned independently into the same SQLite database. The second run adds or updates tracks; it does not replace the first run's data.

## Recommended first test

Run only 25 MP3s from each root first:

```bash
source .venv/bin/activate
git pull
pip install -r requirements.txt

python audio/scan_library.py "/Volumes/WD Passport/Old MacBook Stuff/iTunes Music" --limit 25
python audio/scan_library.py "/Volumes/WD Passport/Music" --limit 25
```

## Full recursive scan

If the test results look sensible:

```bash
source .venv/bin/activate
git pull

python audio/scan_library.py "/Volumes/WD Passport/Old MacBook Stuff/iTunes Music"
python audio/scan_library.py "/Volumes/WD Passport/Music"
```

Both commands write to:

```text
data/audio_library.sqlite
```

The scanner is resumable. On later runs it skips files whose path, size, modification time, and feature-analysis version are unchanged.

To force a fresh analysis of a root:

```bash
python audio/scan_library.py "/Volumes/WD Passport/Music" --force
```

To inventory tags and technical MP3 metadata without decoding audio:

```bash
python audio/scan_library.py "/Volumes/WD Passport/Music" --metadata-only
```

For a faster full-library first pass, shorter excerpts can be used:

```bash
python audio/scan_library.py "/Volumes/WD Passport/Music" --sample-seconds 10
```

The default is three excerpts of up to 20 seconds each per track.
