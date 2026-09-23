import json
import os
import unittest
from unittest.mock import patch

import requests
import app


class OpenAIErrorTests(unittest.TestCase):
    def response(self, code=None, error_type=None, retry_after=None):
        response = requests.Response()
        response.status_code = 429
        response._content = json.dumps({'error': {'code': code, 'type': error_type}}).encode()
        if retry_after:
            response.headers['Retry-After'] = retry_after
        return response

    def test_credits_are_not_reported_as_temporary_rate_limit(self):
        with self.assertRaises(app.AppError) as caught:
            app.check_openai_response(self.response('credit_balance_exhausted', 'insufficient_quota'))
        self.assertIn('credits are exhausted', str(caught.exception))
        self.assertIn('/billing/', caught.exception.help_url)
        self.assertEqual(caught.exception.status_code, 429)

    def test_rate_limit_has_retry_guidance(self):
        with self.assertRaises(app.AppError) as caught:
            app.check_openai_response(self.response('rate_limit_exceeded', retry_after='12'))
        self.assertIn('Wait at least 12 seconds', str(caught.exception))
        self.assertNotIn('credits are exhausted', str(caught.exception))

    def test_spend_limits_and_legacy_quota(self):
        for code, expected in [('project_spend_limit_exceeded', 'project'), ('organization_spend_limit_exceeded', 'organization'), ('organization_usage_limit_exceeded', 'usage limit'), ('insufficient_quota', 'quota')]:
            with self.subTest(code=code), self.assertRaises(app.AppError) as caught:
                app.check_openai_response(self.response(code))
            self.assertIn(expected, str(caught.exception))

    def test_unstructured_429_is_handled(self):
        response = self.response()
        for content in (b'upstream error', b'[]', b'{"error":null}'):
            response._content = content
            with self.assertRaises(app.AppError) as caught:
                app.check_openai_response(response)
            self.assertIn('did not identify', str(caught.exception))

    def test_generate_exposes_billing_action_without_retry_or_spotify(self):
        with patch.object(app, 'APP_PASSWORD', ''), patch.object(app, 'require_configuration'), patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch.object(app.requests, 'post', return_value=self.response('credit_balance_exhausted')) as post, patch.object(app.spotify, 'get_access_token') as spotify, patch.object(app, 'database') as database:
            response = app.app.test_client().post('/api/generate', json={'prompt':'heavy music','source':'discovery'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('credits are exhausted', response.json['error'])
        self.assertIn('/billing/', response.json['help_url'])
        post.assert_called_once()
        spotify.assert_not_called()
        database.assert_not_called()
