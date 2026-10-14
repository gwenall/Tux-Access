import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from PySide6 import QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')
from qt_launcher import Launcher
from download_catalog import Artifact

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def artifact(title='Phasis', upid='phasis-id', platform='linux_x86_64', filename='phasis.deb'):
    return Artifact(upid, title, '1.0', platform, 'x86_64', 12, filename, 'installer', '/mock/ref/id')


class ProductActionTests(unittest.TestCase):
    def setUp(self):
        with patch('arch_package.installed_products', return_value=[]):
            self.window = Launcher()
        self.window._timer.stop()
        self.product = {'title': 'Phasis', 'upid': 'phasis-id'}
        self.window.products = [self.product, {'title': 'Kontakt 8', 'upid': 'kontakt-id'}]
        self.window.render()

    def tearDown(self):
        self.window.close()

    def settle(self):
        deadline = time.monotonic() + 5
        while self.window._busy and time.monotonic() < deadline:
            self.window.poll()
            app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window._busy)

    def test_row_download_fetches_metadata_off_ui_thread_then_scopes_picker(self):
        self.window._token = 'private-mock-session'
        caller = threading.get_ident()
        workers = []
        records = [artifact(), artifact('Kontakt 8', 'kontakt-id', 'win', 'Kontakt.zip')]
        def fetch(token):
            self.assertEqual(token, 'private-mock-session')
            workers.append(threading.get_ident())
            return records
        with patch('download_catalog.available_artifacts', side_effect=fetch), \
             patch.object(self.window, '_show_download_picker') as picker:
            self.window.product_actions[0].click()
            self.settle()
            picker.assert_called_once_with(self.product)
        self.assertNotEqual(workers[0], caller)
        self.assertNotIn('private-mock-session', self.window.status.text())
        matched = [a for a in self.window.artifacts if self.window._artifact_matches(a, self.product)]
        self.assertEqual(matched, [records[0]])

    def test_install_requires_same_session_verified_matching_linux_download(self):
        with patch('arch_package.install_verified_vst') as installer:
            self.window.product_actions[1].click()
            self.assertIn('Download this product', self.window.status.text())
            installer.assert_not_called()
            path = str(Path('mock-verified.deb').resolve())
            # A Windows artifact or other product must not become a native install.
            self.window._verified_files[path] = 'a' * 64
            self.window._verified_artifacts[path] = artifact(platform='win', filename='setup.exe')
            self.window.install_product(self.product)
            installer.assert_not_called()
            self.window._verified_artifacts[path] = artifact(title='Other', upid='other')
            self.window.install_product(self.product)
            installer.assert_not_called()
            self.window._verified_artifacts[path] = artifact()
            installer.return_value = {'title': 'Phasis', 'version': '1.0'}
            with patch('arch_package.installed_products', return_value=[]):
                self.window.install_product(self.product)
                self.settle()
            installer.assert_called_once_with(path, 'a' * 64)

    def test_verified_download_event_enables_matching_row_install(self):
        path = str(Path('downloaded.deb').resolve())
        self.window._events.put(('download', {'path': path, 'sha256': 'b' * 64, 'artifact': artifact()}))
        self.window.poll()
        self.assertEqual(self.window._verified_files[path], 'b' * 64)
        with patch.object(self.window, '_install_verified_path') as install:
            self.window.product_actions[1].click()
            install.assert_called_once_with(path)

    def test_successful_install_merges_status_and_preserves_other_account_rows(self):
        original = list(self.window.products)
        installed = {'title': 'PHASIS', 'version': '2.0', 'type': 3, 'status': 'Installed natively'}
        with patch('arch_package.installed_products', return_value=[installed]):
            self.window._events.put(('install', {'title': 'Phasis', 'version': '2.0'}))
            self.window.poll()
        self.assertEqual(len(self.window.products), 2)
        self.assertIs(self.window.products[0], original[0])
        self.assertIs(self.window.products[1], original[1])
        self.assertEqual(self.window.products[0]['upid'], 'phasis-id')
        self.assertEqual(self.window.products[0]['status'], 'Installed natively')
        self.assertEqual(self.window.products[1]['title'], 'Kontakt 8')
        self.assertEqual(self.window.table.rowCount(), 2)

    def test_windows_install_explains_limitation_and_offline_download_requires_login(self):
        with patch('arch_package.install_verified_vst') as installer:
            self.window.product_actions[3].click()
            self.assertIn('Windows/Wine installation is not available yet', self.window.status.text())
            installer.assert_not_called()
        with patch('download_catalog.available_artifacts') as fetch:
            self.window.product_actions[0].click()
            fetch.assert_not_called()
            self.assertFalse(self.window._busy)

    def test_row_actions_disable_during_worker_even_after_search_render(self):
        release = threading.Event()
        self.window._run('mock work', lambda: release.wait(3) and 'finished', 'error')
        try:
            self.assertTrue(all(not b.isEnabled() for b in self.window.product_actions))
            self.window.search.setText('Phasis')
            self.assertEqual(len(self.window.product_actions), 2)
            self.assertTrue(all(not b.isEnabled() for b in self.window.product_actions))
        finally:
            release.set()
            self.settle()
        self.assertTrue(all(b.isEnabled() for b in self.window.product_actions))


if __name__ == '__main__':
    unittest.main()
