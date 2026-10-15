import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_settings import default_settings
from dataclasses import replace
from download_manager import DownloadCancelled
import removal_coordinator as removal
from wine_manager import WineManager, RECEIPT


@unittest.skipUnless(os.name == 'posix', 'Linux file descriptor removal semantics')
class RemovalTests(unittest.TestCase):
    def fixture(self, root):
        settings = replace(default_settings(), wine_prefix_directory=root / 'prefixes')
        manager = WineManager(settings)
        targets = {'Program Files/Native Instruments/Kontakt 8/Kontakt 8.exe': b'original app',
                   'ProgramData/Native Instruments/Kontakt 8/Resource.bin': b'original resource'}
        hashes = {}
        for relative, value in targets.items():
            target = manager.prefix / 'drive_c' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            hashes[relative] = hashlib.sha256(value).hexdigest()
        (manager.prefix / RECEIPT).write_text(json.dumps({'files': hashes}))
        project = manager.prefix / 'drive_c/users/dev/Documents/My project.nki'
        project.parent.mkdir(parents=True)
        project.write_bytes(b'user work')
        (manager.prefix / 'user.reg').write_text('user preferences')
        record = {**manager._result().to_dict(), 'installed': True}
        return settings, manager, record, targets

    def test_removes_payload_only_and_retains_projects_preferences_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, manager, record, targets = self.fixture(root)
            outside = root / 'personal-project.nki'
            outside.write_text('personal work')
            (manager.prefix / 'drive_c/users/dev/Documents/outside').symlink_to(outside)
            stages = []
            with patch.object(WineManager, 'installation_status', return_value=record), \
                 patch.object(WineManager, '_wine', return_value='/fixture/wine'), \
                 patch.object(WineManager, '_stop_prefix') as stop, \
                 patch('install_coordinator.installed_catalog', return_value=[]):
                result = removal.uninstall_product(record, settings, progress=stages.append)
            self.assertFalse(manager.prefix.exists())
            retained = Path(result['retained_directory'])
            self.assertEqual((retained / 'user.reg').read_text(), 'user preferences')
            self.assertEqual((retained / 'drive_c/users/dev/Documents/My project.nki').read_bytes(), b'user work')
            self.assertTrue((retained / 'drive_c/users/dev/Documents/outside').is_symlink())
            self.assertEqual(outside.read_text(), 'personal work')
            for relative in targets:
                self.assertFalse((retained / 'drive_c' / relative).exists())
            self.assertFalse((retained / RECEIPT).exists())
            self.assertEqual(result['_installed'], [])
            stop.assert_called_once_with('/fixture/wine', manager.prefix, strict=True)
            self.assertEqual(stages[-1]['stage'], 'complete')

    def test_changed_payload_is_preserved_before_stopping_or_moving_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings, manager, record, targets = self.fixture(Path(temporary))
            changed = manager.prefix / 'drive_c' / next(iter(targets))
            changed.write_bytes(b'user edited app')
            with patch.object(WineManager, 'installation_status', return_value=record), \
                 patch.object(WineManager, '_stop_prefix') as stop:
                with self.assertRaisesRegex(removal.RemovalError, 'changed'):
                    removal.uninstall_product(record, settings)
            stop.assert_not_called()
            self.assertEqual(changed.read_bytes(), b'user edited app')

    def test_payload_symlink_is_refused_without_touching_link_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, manager, record, targets = self.fixture(root)
            app = manager.prefix / 'drive_c' / next(iter(targets))
            external = root / 'external'
            external.write_bytes(app.read_bytes())
            app.unlink()
            app.symlink_to(external)
            with patch.object(WineManager, 'installation_status', return_value=record), \
                 patch.object(WineManager, '_stop_prefix') as stop:
                with self.assertRaises(OSError):
                    removal.uninstall_product(record, settings)
            stop.assert_not_called()
            self.assertTrue(app.is_symlink())
            self.assertEqual(external.read_bytes(), b'original app')

    def test_cancel_preserves_installed_files_and_does_not_stop_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings, manager, record, targets = self.fixture(Path(temporary))
            with patch.object(WineManager, '_stop_prefix') as stop:
                with self.assertRaises(DownloadCancelled):
                    removal.uninstall_product(record, settings, cancelled=lambda: True)
            stop.assert_not_called()
            self.assertTrue(manager.prefix.exists())

    def test_forged_record_cannot_remove_an_arbitrary_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings, manager, record, targets = self.fixture(Path(temporary))
            with patch.object(WineManager, 'installation_status', return_value=record), \
                 patch.object(WineManager, '_stop_prefix') as stop:
                with self.assertRaisesRegex(removal.RemovalError, 'verified managed'):
                    removal.uninstall_product({**record, 'prefix': '/unrelated'}, settings)
            stop.assert_not_called()
            self.assertTrue(manager.prefix.exists())

    def test_legacy_and_unknown_products_have_no_removal(self):
        settings = default_settings()
        self.assertFalse(removal.can_uninstall({'title': 'Kontakt 8', 'backend': 'wine', 'managed': False}, settings))
        self.assertFalse(removal.can_uninstall({'title': 'Unknown', 'nativePackage': 'ni-unknown', 'source': 'native-install'}, settings))
        with patch('removal_coordinator.subprocess.run') as run:
            with self.assertRaises(removal.RemovalError):
                removal.uninstall_product({'title': 'Unknown'}, settings)
            run.assert_not_called()

    def test_native_removal_is_one_fixed_package_without_shared_dependencies(self):
        record = {'title': 'Phasis', 'version': '1.2.1', 'source': 'native-install', 'nativePackage': 'ni-phasis'}
        with patch('arch_package.installed_products', return_value=[record]), \
             patch('removal_coordinator.Path.is_file', side_effect=lambda: True), \
             patch('removal_coordinator.subprocess.run') as run:
            run.return_value.returncode = 0
            result = removal._remove_native(record, default_settings(), None, None)
        self.assertEqual(run.call_args.args[0], ['/usr/bin/pkexec', '/usr/bin/pacman', '-R', '--noconfirm', 'native-access-ni-phasis'])
        self.assertEqual(result['status'], 'uninstalled')


if __name__ == '__main__':
    unittest.main()
