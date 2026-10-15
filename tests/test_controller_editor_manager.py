from dataclasses import replace
import unittest
from controller_editor_manager import PROFILE, EXE_TARGET, HARDWARE_SERVICE_TARGET
from ni_application_manager import validate_payload
from wine_manager import WineError


class ControllerEditorProfileTests(unittest.TestCase):
    def test_complete_original_application_and_templates_are_pinned(self):
        rows, hashes = validate_payload(PROFILE)
        self.assertEqual(len(rows), 304)
        self.assertEqual(sum(row['size'] for row in rows), 95031868)
        self.assertEqual(hashes[EXE_TARGET], '0f4326542fdb3211ed39acb973907c82b76b12c45e4e27af9559f19d5f1952d4')
        self.assertEqual(hashes[HARDWARE_SERVICE_TARGET], '88f90c4b378f547508b09f190b4bcb30a35cbc5f5d16a7a0d533267a2c1956d9')
        self.assertEqual(PROFILE.artifact.archive_file_count, 320)
        self.assertEqual(PROFILE.artifact.zip_sha256, '09f7b4fa0e1e038c2890469deeb00e5ae301b16d59caabe831de3382cdecbc5a')

    def test_only_original_selected_install_path_is_registered(self):
        self.assertEqual(len(PROFILE.registry_values), 1)
        value = PROFILE.registry_values[0]
        self.assertEqual(value.name, 'InstallDir')
        self.assertEqual(value.value, 'C:\\Program Files\\Native Instruments\\Controller Editor\\')
        self.assertEqual(value.view, 64)
        self.assertEqual(PROFILE.runtime.size, 25234792)
        self.assertEqual(PROFILE.runtime.arguments, ('/install', '/quiet', '/norestart'))

    def test_hardware_payload_does_not_authorize_unrelated_hardware_files(self):
        rows, hashes = validate_payload(PROFILE)
        changed = [dict(row) for row in rows]
        row = next(row for row in changed if row['target'] == HARDWARE_SERVICE_TARGET)
        row['target'] = 'Program Files/Common Files/Native Instruments/Hardware/OtherService.exe'
        with self.assertRaises(WineError): validate_payload(replace(PROFILE, load_plan=lambda: {'files': changed}))


if __name__ == '__main__': unittest.main()
