# Tune Raider listening worker (experimental)

This is an additive prototype. It accepts **audio that you are authorized to analyze**, not Spotify streams. It does not automate Spotify playback, download protected music, or capture a streaming service.

## Current capabilities

- Decodes a local file or a macOS AVFoundation input into mono float32 PCM using ffmpeg.
- Processes bounded windows, using the existing `scan_library.analyze_samples` implementation for tempo estimates, onset density, frequency balance, loudness, and spectral statistics.
- Aggregates window features and writes a row to `listening_analyses` in the existing SQLite DB.
- Discards decoded audio buffers; no persistent waveform is saved.
- Keeps the existing `tracks` and `track_embeddings` tables unchanged.

It **does not** yet provide AI-based genre labels, instrumental/vocal detection, calibrated BPM, section annotation, or production-ready microphone/stream controls. The tempo measurement is approximate, particularly with short windows and half/double-time rhythms.

## Run from repository root

```bash
source .venv/bin/activate
git pull
pip install -r requirements.txt
brew install ffmpeg
python audio/listen_stream.py --file "/path/to/authorized-recording.wav" --label "artist:title" --seconds 180
```

You can test any ffmpeg-decodable local file, not just MP3.

To list available capture devices on macOS:

```bash
ffmpeg -hide_banner -f avfoundation -list_devices true -i ""
```

For an audio input device whose listed index is `0`:

```bash
python audio/listen_stream.py --device 0 --label "authorized-live-test" --seconds 60
```

The input device must receive audio you have permission to capture and analyze. Device indices vary by machine. No automatic capture routing is configured by this tool.

Change output path with `--db`, the sampling window with `--chunk-seconds`, and the sampling rate with `--sample-rate`.

## Next engineering stages

1. Add tests with synthetic sine/noise/pulse clips; compare stored features against the existing offline scanner.
2. Preserve per-section features and timestamps instead of aggregating only the overall measurement.
3. Add an optional authorized-audio inference pass for trained genre/vocal/instrument models; store provenance and model versions.
4. Connect independently licensed and validated analysis records to Tune Raider's candidate ranking, with a metadata-only fallback.
5. Add a local opt-in job queue with polling, cancel support, and a small track-review screen.

## Constraints

Do not use this worker to analyze Spotify content in violation of Spotify developer policy or user agreements. A system loopback device does not change content rights. This CLI has not been hardware-tested on an actual macOS capture device, and no application UI or continuous background service is installed.
