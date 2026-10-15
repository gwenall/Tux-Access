from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from tux_access.settings import default_settings, load_settings, save_settings, validate_settings, SettingsError


class SettingsTests(unittest.TestCase):
    def test_roundtrip_non_secret_preferences_without_losing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config/settings.json'
            settings = replace(default_settings(), download_directory=root / 'Downloads with spaces', manual_mode=True)
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)
            self.assertEqual(list(path.parent.glob('.settings-*')), [])
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_paths_types_and_nonlocal_reference_rejected(self):
        for changes in ({'download_directory': Path('relative')}, {'download_directory': Path('/safe/../escape')},
                        {'manage_wine': 'true'}, {'reference_endpoint': 'tcp://example.com:5146'},
                        {'wine_executable': 'wine --debug'}, {'content_directory': '/tmp/new\nline'}):
            with self.subTest(changes=changes), self.assertRaises(SettingsError):
                validate_settings(replace(default_settings(), **changes))

    def test_unknown_or_credential_fields_and_corrupt_json_do_not_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            for payload in ('[]', '{invalid', json.dumps({'access_token': 'private-test-secret'})):
                path.write_text(payload)
                with self.assertRaises(SettingsError) as caught:
                    load_settings(path)
                self.assertNotIn('private-test-secret', str(caught.exception))

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink permissions required')
    def test_settings_symlink_is_not_read_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original'
            original.write_text('untouched')
            link = root / 'settings.json'
            link.symlink_to(original)
            with self.assertRaises(SettingsError): load_settings(link)
            with self.assertRaises(SettingsError): save_settings(default_settings(), link)
            self.assertEqual(original.read_text(), 'untouched')


if __name__ == '__main__': unittest.main()
