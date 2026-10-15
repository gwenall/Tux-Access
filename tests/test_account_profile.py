import io
import json
from email.message import Message
import unittest
from unittest.mock import Mock
from account_profile import profile, PROFILE_URL
from account_api import AccountApiError


class Response(io.BytesIO):
    status = 200
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'


class ProfileTests(unittest.TestCase):
    def test_only_requested_name_fields_escape_transport_and_target_is_fixed(self):
        opener = Mock()
        opener.open.return_value = Response(json.dumps({'name': 'Ada Lovelace', 'given_name': 'Ada',
            'email': 'private@example.test', 'sub': 'private-id', 'picture': 'https://example.test/signed'}).encode())
        result = profile('mock-token', opener)
        self.assertEqual(result, {'name': 'Ada Lovelace', 'given_name': 'Ada'})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, PROFILE_URL)
        self.assertEqual(request.get_header('Authorization'), 'Bearer mock-token')

    def test_invalid_token_rejected_before_transport(self):
        opener = Mock()
        with self.assertRaises(ValueError): profile('mock\nunsafe', opener)
        opener.open.assert_not_called()

    def test_invalid_or_oversized_profiles_are_redacted(self):
        for payload in (b'[]', b'invalid-private-text', b' ' * 65537):
            opener = Mock()
            opener.open.return_value = Response(payload)
            with self.assertRaises(AccountApiError) as caught: profile('mock-token', opener)
            self.assertNotIn('private-text', str(caught.exception))


if __name__ == '__main__': unittest.main()
