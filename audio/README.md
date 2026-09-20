# Local audio-library scanner

`scan_library.py` builds a local SQLite index from MP3 files without copying audio into the repository.

Use the newer MacBook Pro for audio indexing and other heavy local compute. The older iMac is intended for prompting and lightweight commands only.

It reads ID3/MP3 metadata and, by default, uses `ffmpeg` to decode three short excerpts from each track (near the beginning, middle, and end). NumPy is then used to calculate lightweight audio features that support similarity search and playlist curation.

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
- optional learned MERT music embeddings

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

```text
/Volumes/WD Passport/Old MacBook Stuff/iTunes Music
/Volumes/WD Passport/Music
```

The scanner is recursive, so nested artist/album folders under each root are included automatically. Both roots write into the same SQLite database.

## Full recursive DSP scan

```bash
source .venv/bin/activate
git pull

python audio/scan_library.py "/Volumes/WD Passport/Old MacBook Stuff/iTunes Music"
python audio/scan_library.py "/Volumes/WD Passport/Music"
```

The scanner is resumable and skips unchanged successfully analyzed files.

## Learned music embeddings

The DSP similarity layer is useful for measurable properties such as tempo, frequency balance, loudness and transient density, but unrelated genres can share those statistics. `build_embeddings.py` adds a higher-level music representation using `m-a-p/MERT-v1-95M`.

Install the optional embedding dependencies on the MacBook Pro only:

```bash
source .venv/bin/activate
git pull
pip install -r requirements-audio-embeddings.txt
```

The first embedding run downloads the MERT model from Hugging Face. The model expects 24 kHz audio. Each track is represented from up to three five-second excerpts spread across the recording. Embeddings are stored in the same local SQLite database and are resumable.

Start with a 25-track test:

```bash
python audio/build_embeddings.py --limit 25
```

Then build the full library:

```bash
python audio/build_embeddings.py
```

The script prefers Apple Metal/MPS acceleration when available. If a model operation fails specifically on MPS, retry with CPU:

```bash
python audio/build_embeddings.py --device cpu
```

Successful existing embeddings are skipped on subsequent runs.

## Similarity search

`find_similar.py` automatically uses MERT embeddings when the seed track has one. Before embeddings exist, it falls back to the original DSP similarity engine.

Use an indexed seed row:

```bash
source .venv/bin/activate
git pull

python audio/find_similar.py --seed-id 3781 --limit 30 --exclude-same-artist
```

Or search by metadata:

```bash
python audio/find_similar.py --artist "Weedeater" --title "Jason... The Dragon" --limit 30 --exclude-same-artist
```

Force a particular engine for comparison:

```bash
python audio/find_similar.py --seed-id 3781 --mode embedding --limit 30 --exclude-same-artist
python audio/find_similar.py --seed-id 3781 --mode dsp --limit 30 --exclude-same-artist
```

Duplicate copies with the same normalized artist/title are collapsed in the results. In embedding mode the ranking is driven by learned music similarity, while the printed `DSP context` remains useful for explaining which conventional acoustic measurements also resemble the seed.
