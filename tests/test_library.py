import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio.library_context import Library
from audio.scan_library import SCHEMA
import app


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'audio.sqlite'
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
            for i, (artist, title, bass, error) in enumerate([
                ('A', 'Quiet', .1, None), ('B', 'Heavy', .9, None),
                ('B', 'Heavy', .9, None), ('C', 'Broken', .5, 'decode failed'),
                ('D', 'Unknown', None, None),
            ]):
                conn.execute('INSERT INTO tracks(path,file_size,mtime_ns,feature_version,analyzed_at,artist,title,low_energy_ratio,error) VALUES(?,1,1,1,?,?,?,?,?)',
                             (str(i), '2026-09-21', artist, title, bass, error))

    def tearDown(self):
        self.temp.cleanup()

    def test_retrieval_dedupes_excludes_and_ranks_sound(self):
        library = Library(self.db)
        self.assertEqual(len(library.rows), 3)
        results = library.candidates({'sound': {'bass_weight': 100}})
        self.assertEqual(results[0]['title'], 'Heavy')
        self.assertNotIn('bass_weight', results[-1]['sound_percentiles'])
        self.assertEqual(library.candidates({}, ['b - heavy'])[0]['title'], 'Quiet')
        self.assertNotIn('Heavy', [r['title'] for r in library.candidates({}, ['B - Heavy'])])
        self.assertNotIn('path', results[0])

    def test_selection_rejects_invented_ids(self):
        with self.assertRaises(ValueError):
            Library.validate_selection({'tracks': [{'id': 999}]}, Library(self.db).candidates({}))

    def test_library_model_returns_canonical_metadata(self):
        candidate = Library(self.db).candidates({})[0]
        with patch.object(app, 'AUDIO_DATABASE', self.db), patch.object(app, 'model_json', side_effect=[{}, {'name': 'Test', 'tracks': [{'id': candidate['id'], 'artist': 'Invented'}]}]):
            result = app.ask_for_library_playlist('quiet music')
        self.assertEqual(result['tracks'][0]['artist'], 'A')

    def test_generate_persists_library_scores_and_dedupes_spotify(self):
        candidate = Library(self.db).candidates({})[0]
        generated = {'name': 'Test', 'tracks': [candidate, candidate]}
        resolved = {'uri': 'spotify:track:one', 'name': 'Quiet', 'artists': [{'name': 'A'}]}
        with patch.object(app, 'DATABASE', Path(self.temp.name) / 'history.sqlite'), \
             patch.object(app, 'require_configuration'), \
             patch.object(app, 'ask_for_library_playlist', return_value=generated), \
             patch.object(app.spotify, 'get_access_token', return_value='test'), \
             patch.object(app.spotify, 'search_track', return_value=resolved), \
             patch.object(app.spotify, 'create_playlist', return_value={'id': 'one'}), \
             patch.object(app.spotify, 'add_items') as add:
            response = app.app.test_client().post('/api/generate', json={'prompt': 'quiet music'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['source'], 'library')
            add.assert_called_once_with('test', 'one', ['spotify:track:one'])
            saved = app.app.test_client().get('/api/history').json[0]
            self.assertEqual(saved['source_tracks'][0]['sound_percentiles'], candidate['sound_percentiles'])

    def test_missing_database_does_not_create_file(self):
        path = Path(self.temp.name) / 'missing.sqlite'
        with self.assertRaises(ValueError):
            Library(path)
        self.assertFalse(path.exists())

    def test_history_migrates_and_regenerates_original_source(self):
        history = Path(self.temp.name) / 'history.sqlite'
        with sqlite3.connect(history) as conn:
            conn.execute('CREATE TABLE generated_playlists(id INTEGER PRIMARY KEY,prompt TEXT,name TEXT,description TEXT,tracks TEXT,spotify_url TEXT,created_at TEXT)')
            conn.execute("INSERT INTO generated_playlists VALUES(1,'test','test','test','[]',NULL,'today')")
        with patch.object(app, 'DATABASE', history):
            with app.database() as conn:
                self.assertEqual(conn.execute('SELECT source FROM generated_playlists').fetchone()[0], 'discovery')
                conn.execute('UPDATE generated_playlists SET source=?,source_tracks=? WHERE id=1', ('library', json.dumps([{'artist': 'B', 'title': 'Heavy'}])))
            with patch.object(app, 'create_from_prompt', return_value={}) as create:
                response = app.app.test_client().post('/api/history/1/regenerate')
                self.assertEqual(response.status_code, 200)
                create.assert_called_once_with('test', ['B - Heavy'], 'library')


if __name__ == '__main__':
    unittest.main()
