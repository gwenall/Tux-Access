"""Collection navigation and individual actions without downloads or credentials."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
try:
    from PySide6 import QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')
from tux_access.settings import default_settings
from tux_access.downloads.catalog import Artifact
from tux_access.ui.main_window import Launcher

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class BundleUiTests(unittest.TestCase):
    def setUp(self):
        with patch('tux_access.settings.load_settings', return_value=default_settings()), \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window = Launcher()
        self.window._timer.stop()
        self.settle()
        self.massive_id = '02cf2683-8802-4ccc-b7c4-78c89f7d3fad'
        self.kontakt_id = '0e504595-40d8-4982-978e-a242f036912d'
        self.bundle = {'title': 'KOMPLETE 13', 'upid': 'a3f6622b-00c5-49af-bb0d-2a5ec004e91c', 'type': 5,
                       'bundleMembers': [{'title': 'Massive', 'upid': self.massive_id},
                                         {'title': 'Kontakt 8', 'upid': self.kontakt_id},
                                         {'title': 'Fixture library', 'upid': 'fixture-library'}]}
        self.massive = {'title': 'Massive', 'upid': self.massive_id, 'type': 1}
        self.library = {'title': 'Fixture library', 'upid': 'fixture-library', 'type': 2}
        self.outsider = {'title': 'Unrelated owned product', 'upid': 'unrelated-product'}
        self.window._load_account_rows([self.bundle, self.massive, self.library, self.outsider])
        self.window.artifacts = [Artifact(self.massive_id, 'Massive', '1.7.0', 'pc', 'any', 12,
                                         'Massive_Installer.zip', 'installer', '/private-massive'),
                                 Artifact('fixture-library', 'Fixture library', '1.0', 'pc', 'any', 12,
                                          'Library.zip', 'installer', '/private-library')]
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

    def action(self, title):
        return self.window._bundle_actions[next(index for index, product in enumerate(self.window._bundle_rows)
                                               if product['title'] == title)]

    def test_bundle_view_is_embedded_and_contains_only_confirmed_members_without_bulk_work(self):
        self.window._token = 'private-token'
        original_artifacts = self.window.artifacts
        original_artwork = self.window.sidebar_art.source_path
        self.assertEqual(self.window.product_actions[0].text(), 'View products')
        with patch.object(QtWidgets.QDialog, 'exec') as modal, \
             patch('tux_access.installation.install.install_product') as install, \
             patch.object(self.window, 'download_artifact') as download:
            self.window.product_actions[0].click()
            self.assertIs(self.window.pages.currentWidget(), self.window._bundle_page)
            self.assertEqual({product['title'] for product in self.window._bundle_rows},
                             {'Massive', 'Kontakt 8', 'Fixture library'})
            labels = '\n'.join(label.text() for label in self.window._bundle_page.findChildren(QtWidgets.QLabel))
            self.assertIn('no single application installer', labels)
            self.assertIn('explicit bundle metadata supplied with this catalog record', labels)
            self.assertNotIn('14 October 2026', labels)
            self.assertIn('does not establish download authorization', labels)
            self.assertNotIn('Unrelated owned product', labels)
            self.assertEqual(self.action('Massive').text(), 'Install')
            self.assertEqual(self.action('Kontakt 8').text(), 'Show options')
            self.assertEqual(self.action('Fixture library').text(), 'Show options')
            install.assert_not_called()
            download.assert_not_called()
            modal.assert_not_called()
        self.assertIs(self.window.artifacts, original_artifacts)
        self.assertEqual(self.window._token, 'private-token')
        self.assertEqual(self.window.sidebar_art.source_path, original_artwork)
        self.window.set_view('all')
        self.assertIs(self.window.pages.currentWidget(), self.window.library_page)

    def test_defensive_bundle_install_opens_page_and_unknown_membership_does_not_use_owned_rows(self):
        unknown = {'title': 'Other collection', 'upid': 'unknown-bundle', 'type': 5}
        with patch('tux_access.installation.install.install_product') as install:
            self.window.install_product(self.bundle)
            self.assertIs(self.window.pages.currentWidget(), self.window._bundle_page)
            self.window.install_product(unknown)
            self.assertEqual(self.window.bundle_table.rowCount(), 0)
            self.assertIn('Confirmed membership is not available', self.window.bundle_notice.text())
            self.assertIn('unrelated owned products are not substituted', self.window.bundle_notice.text())
            install.assert_not_called()

    def test_collection_refresh_is_reload_icon_and_membership_source_tracks_selected_metadata(self):
        reference = {key: value for key, value in self.bundle.items() if key != 'bundleMembers'}
        self.window.show_bundle(reference)
        button = self.window.bundle_refresh_button
        self.assertEqual(button.text(), '')
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.toolTip(), 'Refresh collection')
        self.assertEqual(button.accessibleName(), 'Refresh collection')
        self.assertIn('snapshot dated 14 October 2026', self.window.bundle_explanation.text())
        self.window.show_bundle(self.bundle)
        self.assertIn('explicit bundle metadata', self.window.bundle_explanation.text())
        self.assertNotIn('snapshot dated', self.window.bundle_explanation.text())
        self.assertEqual(self.window.bundle_table.rowCount(), 3)

    def test_member_install_runs_one_authorized_pipeline_and_keeps_bundle_footer_available(self):
        self.window._token = 'private-token'
        self.window.show_bundle(self.bundle)
        entered, release = threading.Event(), threading.Event()
        seen = []
        def pipeline(product, token, settings, **options):
            seen.append(product['upid'])
            self.assertEqual(token, 'private-token')
            self.assertIs(product['bundleInstallerAvailable'], True)
            options['progress']('download', 3, 10, 'Downloading Massive…')
            entered.set()
            release.wait(3)
            return {'title': 'Massive', 'version': '1.7.0', 'backend': 'wine', 'activation': 'unverified'}
        local = {'title': 'Massive', 'version': '1.7.0', 'backend': 'wine', 'status': 'Installed · activation unverified'}
        with patch('tux_access.installation.install.install_product', side_effect=pipeline) as install, \
             patch('tux_access.installation.install.installed_catalog', return_value=[local]):
            self.action('Massive').click()
            try:
                self.assertTrue(entered.wait(1))
                self.window.poll()
                self.assertTrue(self.window._busy)
                self.assertTrue(self.window.cancel_button.isEnabled())
                self.assertTrue(all(not button.isEnabled() for button in self.window._bundle_actions))
                self.assertIs(self.window.pages.currentWidget(), self.window._bundle_page)
                self.assertEqual(self.window.progress.value(), 30)
            finally:
                release.set()
                self.settle()
            install.assert_called_once()
        self.assertEqual(seen, [self.massive_id])
        self.assertEqual(self.action('Massive').text(), 'Launch')

    def test_missing_authorization_and_unsupported_member_options_are_visible_without_install(self):
        self.window.show_bundle(self.bundle)
        with patch('tux_access.installation.install.install_product') as install:
            self.action('Kontakt 8').click()
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            text = '\n'.join(label.text() for label in self.window._settings_page.findChildren(QtWidgets.QLabel))
            self.assertIn('no authorized installer', text)
            self.window.show_bundle(self.bundle)
            self.action('Fixture library').click()
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            text = '\n'.join(label.text() for label in self.window._settings_page.findChildren(QtWidgets.QLabel))
            self.assertIn('Fixture library installation is not available yet', text)
            install.assert_not_called()

    def test_installed_member_launches_exact_local_record_and_missing_authorization_cannot_install(self):
        record = {'title': 'Massive', 'version': '1.7.0', 'backend': 'wine', 'managed': True,
                  'status': 'Installed · activation unverified', 'prefix': '/known/massive', 'receipt': '/known/receipt'}
        self.window._merge_installed([record])
        self.window.show_bundle(self.bundle)
        self.assertEqual(self.action('Massive').text(), 'Launch')
        with patch('tux_access.installation.wine.massive.MassiveManager') as manager:
            manager.return_value.launch_record.return_value.pid = 123
            self.action('Massive').click()
            self.settle()
            passed = manager.return_value.launch_record.call_args.args[0]
            self.assertEqual(passed['prefix'], '/known/massive')
        missing = next(product for product in self.window._bundle_rows if product['title'] == 'Kontakt 8')
        with patch('tux_access.installation.install.install_product') as install:
            self.window.install_product(missing)
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
