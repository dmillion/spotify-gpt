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

## Acoustic similarity search

`find_similar.py` compares one indexed seed track against the successfully analyzed library using the stored DSP features. Features are robustly normalized across the local collection, weighted, and combined into an acoustic-distance score.

This is intended as a first-pass candidate generator for playlist curation. The score is relative similarity within the indexed library, not a probability and not a semantic genre judgment.

Search for a seed using artist/title text:

```bash
source .venv/bin/activate
git pull

python audio/find_similar.py --artist "Weedeater" --title "God Luck and Good Speed"
```

Or use a free-text seed search:

```bash
python audio/find_similar.py "Droids Attack Steven Seagal"
```

Return more candidates:

```bash
python audio/find_similar.py "Droids Attack Steven Seagal" --limit 50
```

Exclude other songs by the seed artist so the list is more useful for discovery:

```bash
python audio/find_similar.py "Droids Attack Steven Seagal" --limit 50 --exclude-same-artist
```

If a search matches multiple tracks, the script prints their SQLite row IDs. Re-run with the desired ID:

```bash
python audio/find_similar.py --seed-id 1234 --limit 50 --exclude-same-artist
```

An exact indexed file can also be used:

```bash
python audio/find_similar.py --path "/Volumes/WD Passport/Music/Artist/Album/song.mp3" --limit 50
```

The output shows a relative similarity score and the three measured characteristics that are closest to the seed (for example tempo, bass weight, fuzz/noise texture, brightness, or rhythmic density).

The next planned layer is learned audio embeddings, which should capture higher-level timbre and musical similarity that these hand-designed DSP measurements cannot fully represent.
