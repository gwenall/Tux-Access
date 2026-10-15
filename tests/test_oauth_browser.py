import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

try:
    from PySide6 import QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')

from account_auth import APP_REDIRECT, BROWSER_REDIRECT, exchange_code
from oauth_browser import browser_login_dialog, register_browser_callback, HANDLER_ID
from oauth_callback import forward_callback

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@unittest.skipUnless(sys.platform == 'linux', 'Linux browser callbacks required')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = Path(self.directory.name) / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.urls = []
        self.dialog = browser_login_dialog(
            opener=lambda url: self.urls.append(url) or True,
            prepare_handler=lambda: None, runtime_dir=self.runtime)
        self.dialog.start()

    def tearDown(self):
        self.dialog.cleanup()
        self.dialog.close()
        self.directory.cleanup()

    def test_relay_validates_state_and_redeems_with_original_https_redirect(self):
        query = parse_qs(urlsplit(self.urls[0]).query)
        self.assertEqual(query['redirect_uri'], [BROWSER_REDIRECT])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        # NI's HTTPS relay preserves query parameters at the native target.
        callback = APP_REDIRECT + '?' + urlencode({'code':'mock-code','state':query['state'][0]})
        self.assertTrue(forward_callback(callback, self.runtime))
        self.dialog.poll_callbacks()
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.code, 'mock-code')
        self.assertFalse((self.runtime / 'native-access-linux-oauth/callback.sock').exists())
        def provider(method, url, headers, body):
            values = parse_qs(body.decode())
            self.assertEqual(values['redirect_uri'], [BROWSER_REDIRECT])
            self.assertEqual(values['code'], ['mock-code'])
            return {'access_token':'mock-token'}
        exchange_code(self.dialog.code, self.dialog.verifier, provider, self.dialog.redirect_uri)

    def test_wrong_state_cannot_accept_and_cancellation_closes_receiver(self):
        self.assertTrue(forward_callback(APP_REDIRECT + '?code=mock-code&state=wrong', self.runtime))
        self.dialog.poll_callbacks()
        self.assertIsNone(self.dialog.code)
        self.assertNotEqual(self.dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.dialog.reject()
        self.assertFalse((self.runtime / 'native-access-linux-oauth/callback.sock').exists())

    def test_expired_transaction_cannot_accept_callback(self):
        self.dialog.deadline = 0
        self.assertTrue(forward_callback(APP_REDIRECT + '?' + urlencode({'code':'mock','state':self.dialog.state}), self.runtime))
        self.dialog.poll_callbacks()
        self.assertIsNone(self.dialog.code)
        self.assertFalse((self.runtime / 'native-access-linux-oauth/callback.sock').exists())

    def test_switch_account_requests_fresh_provider_login(self):
        self.dialog.cleanup()
        self.dialog = browser_login_dialog(
            opener=lambda url: self.urls.append(url) or True,
            prepare_handler=lambda: None, runtime_dir=self.runtime, force_login=True)
        self.dialog.start()
        self.assertEqual(parse_qs(urlsplit(self.urls[-1]).query)['prompt'], ['login'])

    def test_browser_open_failure_retries_inline_with_new_state_and_cleans_receiver(self):
        self.dialog.cleanup()
        opened = []
        def opener(url):
            opened.append(url)
            return len(opened) > 1
        self.dialog = browser_login_dialog(
            opener=opener, prepare_handler=lambda: None, runtime_dir=self.runtime)
        self.dialog.start()
        state = self.dialog.state
        self.assertFalse(self.dialog.retry_button.isHidden())
        self.assertFalse((self.runtime / 'native-access-linux-oauth/callback.sock').exists())
        self.dialog.retry_button.click()
        self.assertNotEqual(self.dialog.state, state)
        self.assertEqual(len(opened), 2)
        self.assertTrue(self.dialog.retry_button.isHidden())
        self.assertTrue((self.runtime / 'native-access-linux-oauth/callback.sock').exists())

    def test_desktop_handler_uses_callback_cli_without_embedding_values(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': self.directory.name}), patch('oauth_browser.subprocess.run') as command:
            command.return_value.returncode = 0
            register_browser_callback()
        text = (Path(self.directory.name) / 'applications' / HANDLER_ID).read_text()
        self.assertIn('--oauth-callback %u', text)
        self.assertIn('MimeType=x-scheme-handler/native-access;', text)
        self.assertNotIn(self.dialog.state, text)
        self.assertNotIn(self.dialog.verifier, text)


if __name__ == '__main__':
    unittest.main()
