"""Report API rejection details without leaking credentials or raw responses."""
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imitation_agent import HaikuTools
from researcher_teaching import TeachingError


class HaikuErrorTests(unittest.TestCase):
    def error(self, body):
        client=HaikuTools(SimpleNamespace(key='test-secret-key'))
        error=HTTPError('https://api.anthropic.com/v1/messages',400,'Bad Request',{},io.BytesIO(body))
        with patch('imitation_agent.urllib.request.urlopen',side_effect=error) as request:
            with self.assertRaises(TeachingError) as caught:client.complete({'model':'test'})
            self.assertEqual(request.call_count,1)
        return str(caught.exception)

    def test_reports_reason_without_echoed_key_or_raw_fields(self):
        message=self.error(json.dumps(dict(error=dict(type='invalid_request_error',message='Rejected test-secret-key'),
                                          headers=dict(secret='raw-header'))).encode())
        self.assertIn('invalid_request_error: Rejected [REDACTED]',message)
        self.assertNotIn('test-secret-key',message)
        self.assertNotIn('raw-header',message)

    def test_non_json_error_has_useful_fallback(self):
        self.assertIn('HTTP 400',self.error(b'<html>error</html>'))

    def test_message_length_bounded(self):
        self.assertLess(len(self.error(json.dumps(dict(error=dict(message='x'*10000))).encode())),750)


if __name__=='__main__':unittest.main()
