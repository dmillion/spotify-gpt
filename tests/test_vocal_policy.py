import unittest
from unittest.mock import patch
import requests
import vocal_policy as policy


class VocalPolicyTests(unittest.TestCase):
    def setUp(self):
        policy.track_evidence.cache_clear()
        lrclib_mock = patch.object(policy.lrclib_client, 'evidence', return_value=None)
        lrclib_mock.start()
        self.addCleanup(lrclib_mock.stop)

    def test_strict_intent_and_negations(self):
        for prompt in ("Give me songs like 'Nineteen' by Karma to Burn, instrumental only", 'only instrumental stoner rock', 'no vocals', 'without singing', 'vocal-free music'):
            with self.subTest(prompt=prompt):
                self.assertTrue(policy.requires_instrumental(prompt))
        for prompt in ('mostly instrumental', 'not instrumental only', "don't avoid vocals", 'avoid instrumental songs', 'some instrumentals and some vocals', 'songs like "Instrumental Only"', 'instrumental passages with singing'):
            with self.subTest(prompt=prompt):
                self.assertFalse(policy.requires_instrumental(prompt))

    def test_unknown_and_vocal_tracks_cannot_fill_strict_playlist(self):
        tracks = [{'artist':'A', 'title':title} for title in ('Instrumental', 'Vocal', 'Unknown')]
        with patch.object(policy, 'track_evidence', side_effect=[{'status':'instrumental','source':'test'}, {'status':'vocal'}, {'status':'unknown'}]):
            kept, rejected = policy.filter_tracks('instrumental only', tracks)
        self.assertEqual([t['title'] for t in kept], ['Instrumental'])
        self.assertEqual(len(rejected), 2)
        self.assertEqual(kept[0]['instrumental_evidence']['source'], 'test')

    def test_no_lookups_for_unconstrained_prompt(self):
        tracks = [{'artist':'A','title':'Song'}]
        with patch.object(policy, 'track_evidence') as lookup:
            self.assertEqual(policy.filter_tracks('heavy riffs',tracks), (tracks, []))
        lookup.assert_not_called()

    def test_missing_service_fails_closed(self):
        with patch.object(policy, 'track_evidence', side_effect=requests.Timeout):
            with self.assertRaisesRegex(ValueError, 'No tracks were written'):
                policy.enforce_resolved('no vocals', [{'artists':[{'name':'A'}], 'name':'Song'}])

    def test_spotify_match_is_checked_independently(self):
        resolved = [{'artists':[{'name':'Other artist'}], 'name':'Vocal mix', 'uri':'spotify:track:wrong'}]
        with patch.object(policy, 'track_evidence', return_value={'status':'unknown'}) as lookup:
            with self.assertRaises(ValueError):
                policy.enforce_resolved('instrumental only', resolved)
        lookup.assert_called_once_with('Other artist','Vocal mix')

    def test_explicit_version_not_bare_title(self):
        with patch.object(policy, '_lastfm_evidence', return_value=None), patch.object(policy, '_musicbrainz_evidence', return_value=None):
            self.assertEqual(policy.track_evidence('A','Song (Instrumental)')['status'],'instrumental')
            self.assertEqual(policy.track_evidence('A','Instrumental')['status'],'unknown')

    def test_conflicting_metadata_rejects_track(self):
        with patch.object(policy, '_lastfm_evidence', return_value={'status':'instrumental'}), patch.object(policy, '_musicbrainz_evidence', return_value={'status':'vocal'}):
            self.assertEqual(policy.track_evidence('A','Song')['status'], 'vocal')

    def test_artist_genre_is_not_evidence(self):
        tracks = [{'artist':'Instrumental band','title':'Song','genre':'instrumental','instrumental':True}]
        with patch.object(policy, 'track_evidence', return_value={'status':'unknown'}):
            self.assertEqual(policy.filter_tracks('instrumental only',tracks)[0], [])

    def test_musicbrainz_identity_and_work_metadata(self):
        search = {'recordings':[{'id':'recording','title':'Song','artist-credit':[{'artist':{'name':'A'}}]}]}
        relations = {'relations':[{'type':'performance','work':{'id':'work','languages':['zxx']}}]}
        with patch.object(policy.musicbrainz, 'ENABLED', True), patch.object(policy.musicbrainz, '_request', side_effect=[search,relations]) as lookup:
            self.assertEqual(policy._musicbrainz_evidence('A','Song')['status'], 'instrumental')
            self.assertEqual(lookup.call_count,2)
        relations['relations'].append({'type':'vocal'})
        with patch.object(policy.musicbrainz, 'ENABLED', True), patch.object(policy.musicbrainz, '_request', side_effect=[search,relations]):
            self.assertEqual(policy._musicbrainz_evidence('A','Song')['status'], 'vocal')
        with patch.object(policy.musicbrainz, 'ENABLED', True), patch.object(policy.musicbrainz, '_request', return_value=search) as lookup:
            self.assertIsNone(policy._musicbrainz_evidence('Wrong artist','Song'))
            self.assertEqual(lookup.call_count,1)


class PlaylistBoundaryTests(unittest.TestCase):
    def test_generation_never_writes_unverified_resolved_tracks(self):
        import app
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temp, patch.object(app,'DATABASE',Path(temp)/'history.sqlite'), patch.object(app,'require_configuration'), patch.object(app,'ask_for_hybrid_playlist',return_value={'name':'Test','tracks':[{'artist':'A','title':'Instrumental song'}]}), patch.object(app.spotify,'get_access_token',return_value='test'), patch.object(app.spotify,'search_track',return_value={'artists':[{'name':'A'}],'name':'Vocal mix','uri':'bad'}), patch.object(policy,'track_evidence',return_value={'status':'unknown'}), patch.object(app.spotify,'create_playlist') as create, patch.object(app.spotify,'add_items') as add:
            with self.assertRaisesRegex(app.AppError, 'Instrumental constraint'):
                app.create_from_prompt('instrumental only')
        create.assert_not_called()
        add.assert_not_called()
