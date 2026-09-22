"""Read-only retrieval and interpretable, library-relative acoustic profiles."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np

AXES = {
    'bass_weight': 'low_energy_ratio',
    'low_mid_weight': 'low_mid_energy_ratio',
    'brightness': 'spectral_centroid_hz',
    'noise_texture': 'spectral_flatness',
    'loudness': 'rms_dbfs',
    'rhythmic_density': 'onset_density',
    'tempo': 'tempo_bpm',
}


def key(artist, title):
    return f'{artist.strip().casefold()} - {title.strip().casefold()}'


class Library:
    def __init__(self, path: Path):
        if not path.is_file():
            raise ValueError('The MP3 index is missing. Scan your library or choose discovery mode.')
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            self.rows = [dict(r) for r in conn.execute(
                "SELECT rowid AS id, * FROM tracks WHERE error IS NULL AND artist != '' AND title != '' ORDER BY path"
            )]
        # Normalize over unique artist/title pairs so duplicate copies do not skew scores.
        unique = {}
        for row in self.rows:
            unique.setdefault(key(row['artist'], row['title']), row)
        self.rows = list(unique.values())
        if not self.rows:
            raise ValueError('The MP3 index has no usable tracks. Scan your library first.')
        for row in self.rows:
            row['profile'] = {}
        for axis, column in AXES.items():
            values = np.asarray(sorted(float(r[column]) for r in self.rows if self.valid(r[column])))
            for row in self.rows:
                value = row[column]
                if self.valid(value):
                    # Midrank percentiles keep ties together; a constant feature scores 50.
                    left = np.searchsorted(values, value, side='left')
                    right = np.searchsorted(values, value, side='right')
                    row['profile'][axis] = round(100 * (left + right) / (2 * len(values)))

    @staticmethod
    def valid(value):
        return isinstance(value, (int, float)) and math.isfinite(value)

    def summary(self):
        return {
            'tracks': len(self.rows),
            'artists': sorted({r['artist'] for r in self.rows}),
            'genres': sorted({r['genre'] for r in self.rows if r['genre']}),
            'axes': list(AXES),
        }

    def candidates(self, plan, excluded=(), limit=240):
        if not isinstance(plan, dict):
            raise ValueError('The library search plan was invalid. Please try again.')
        artists = plan.get('artists', [])
        terms = plan.get('terms', [])
        targets = plan.get('sound', {})
        if not isinstance(artists, list) or not isinstance(terms, list) or not isinstance(targets, dict):
            raise ValueError('The library search plan was invalid. Please try again.')
        artists = {s.casefold() for s in artists if isinstance(s, str)}
        terms = [s.casefold() for s in terms if isinstance(s, str) and s.strip()]
        targets = {k: float(v) for k, v in targets.items() if k in AXES and self.valid(v) and 0 <= v <= 100}
        excluded = {s.strip().casefold() for s in excluded}
        ranked = []
        for row in self.rows:
            if key(row['artist'], row['title']) in excluded:
                continue
            text = ' '.join(str(row.get(k) or '') for k in ('artist', 'title', 'album', 'genre', 'date')).casefold()
            score = 3 * (row['artist'].casefold() in artists) + sum(term in text for term in terms)
            if targets:
                # Missing measurements receive maximum distance, never an invented score.
                score += 2 * (1 - sum(abs(row['profile'][k] - v) / 100 if k in row['profile'] else 1 for k, v in targets.items()) / len(targets))
            ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], item[1]['id']))
        # Round-robin within equal relevance gives broad prompts artist diversity.
        buckets = {}
        for score, row in ranked:
            buckets.setdefault(score, {}).setdefault(row['artist'], []).append(row)
        selected = []
        for group in buckets.values():
            while group and len(selected) < limit:
                for artist in list(group):
                    selected.append(group[artist].pop(0))
                    if not group[artist]:
                        del group[artist]
                    if len(selected) >= limit:
                        break
        return [self.public(row) for row in selected]

    @staticmethod
    def public(row):
        return {**{k: row[k] for k in ('id', 'artist', 'title', 'album', 'genre', 'date', 'duration_seconds', 'tempo_bpm')},
                'sound_percentiles': row['profile']}

    @staticmethod
    def validate_selection(payload, candidates):
        allowed = {r['id']: r for r in candidates}
        selected, seen = [], set()
        tracks = payload.get('tracks')
        if not isinstance(tracks, list) or not tracks:
            raise ValueError('No library tracks matched the request. Try a broader prompt.')
        for track in tracks:
            track_id = track.get('id') if isinstance(track, dict) else None
            if type(track_id) is not int or track_id not in allowed:
                raise ValueError('The model selected a track outside the library candidates. Please try again.')
            if track_id not in seen:
                selected.append(allowed[track_id])
                seen.add(track_id)
        payload['tracks'] = selected
        return payload
