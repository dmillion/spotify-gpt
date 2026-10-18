# LRCLIB instrumental verification

LRCLIB is an additional, free evidence source for Tune Raider's strict "instrumental only", "no vocals", and equivalent prompts. It is not queried for unrestricted prompts.

## Verification sequence

- Existing Last.fm track tags, MusicBrainz recording/work relationships, and optional web label checks run first.
- If no track-level determination is available, query LRCLIB by artist/title and, when Spotify provides them, album and exact duration.
- `/api/get` uses all four signature attributes. LRCLIB allows at most a two-second duration difference.
- If no exact lookup succeeds or album/duration isn't known, search `/api/search`. Reject mismatched artist/title/album/duration entries and conflicting matches.
- Accept only a literal `instrumental: true` with no contradictory lyrics fields. `instrumental: false` is treated conservatively as vocal/nonqualifying.
- No record, errors, and ambiguous matches leave a song unverified. Under strict requests, unknowns are excluded as before.

No lyrics bodies are saved or sent to models. Evidence stores LRCLIB record links. The API requires identifying User-Agent headers. Requests are sequential and spaced at least 300ms; 429 Retry-After is honored by suspending LRCLIB lookups until that interval has passed.

## Configuration

No API key is needed. Existing `requests` dependency suffices.

```bash
source .venv/bin/activate
git pull
python -m unittest discover -s tests -v
```

## Limitations

LRCLIB is crowdsourced; an instrumental flag is useful metadata evidence, not proof that no audible spoken samples or singing exist. Track identity is particularly important for instrumental mixes, alternate recordings, remasters, and live versions. LRCLIB matching doesn't independently inspect audio. We intentionally avoid treating missing lyrics as evidence of an instrumental recording.
