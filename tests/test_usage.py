import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import app


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in [('DATABASE', Path(self.temp.name) / 'history.sqlite'), ('APP_PASSWORD', '')]:
            patcher = patch.object(app, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {'OPENAI_API_KEY': 'test'})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.app.test_client()

    def call_model(self, content='{}', usage=True):
        payload = {'model': 'test-model', 'choices': [{'message': {'content': content}}]}
        if usage:
            payload['usage'] = {'prompt_tokens': 100, 'completion_tokens': 25, 'total_tokens': 125}
        with patch.object(app.requests, 'post', return_value=Mock(json=lambda: payload)):
            return app.model_json('instructions', 'prompt')

    def test_empty_and_persistent_totals_across_calls(self):
        self.assertEqual(self.client.get('/api/usage').json['total_tokens'], 0)
        self.call_model()
        self.call_model()
        usage = app.app.test_client().get('/api/usage').json
        self.assertEqual((usage['input_tokens'], usage['output_tokens'], usage['total_tokens']), (200, 50, 250))
        self.assertEqual(usage['requests'], 2)
        self.assertEqual(usage['today_tokens'], 250)
        self.assertEqual(usage['latest']['model'], 'test-model')

    def test_invalid_content_still_records_usage(self):
        with self.assertRaises(app.AppError):
            self.call_model('invalid JSON')
        self.assertEqual(self.client.get('/api/usage').json['total_tokens'], 125)

    def test_missing_usage_is_unknown(self):
        self.call_model(usage=False)
        usage = self.client.get('/api/usage').json
        self.assertEqual(usage['unreported_requests'], 1)
        self.assertIsNone(usage['latest']['total_tokens'])

    def test_http_failure_does_not_invent_usage(self):
        with patch.object(app.requests, 'post', return_value=Mock(raise_for_status=Mock(side_effect=requests.HTTPError))):
            with self.assertRaises(requests.HTTPError):
                app.model_json('instructions', 'prompt')
        self.assertEqual(self.client.get('/api/usage').json['requests'], 0)

    def test_today_excludes_previous_days(self):
        self.call_model()
        with app.database() as connection:
            connection.execute("UPDATE openai_usage SET created_at='2000-01-01T00:00:00+00:00'")
        self.call_model()
        usage = self.client.get('/api/usage').json
        self.assertEqual(usage['today_tokens'], 125)
        self.assertEqual(usage['total_tokens'], 250)

    def test_usage_requires_login_when_enabled(self):
        with patch.object(app, 'APP_PASSWORD', 'test'):
            self.assertEqual(self.client.get('/api/usage').status_code, 401)
