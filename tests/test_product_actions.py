"""Install-first desktop behavior without credentials, network or elevation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')
from tux_access.ui.main_window import Launcher
from tux_access.settings import default_settings
from tux_access.downloads.manager import DownloadCancelled

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class ProductActionTests(unittest.TestCase):
    def setUp(self):
        profile_patch = patch('tux_access.auth.profile.profile', return_value={})
        self.addCleanup(profile_patch.stop)
        self.profile_mock = profile_patch.start()
        artifacts_patch = patch('tux_access.downloads.catalog.available_artifacts', return_value=[])
        self.addCleanup(artifacts_patch.stop)
        self.artifacts_mock = artifacts_patch.start()
        with patch('tux_access.settings.load_settings', return_value=default_settings()), \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window = Launcher()
        self.window._timer.stop()
        self.settle()
        self.product = {'title': 'Phasis', 'upid': 'phasis-id'}
        self.other = {'title': 'Unsupported synthesizer', 'upid': 'other-id'}
        self.window.products = [self.product, self.other]
        self.window.render()

    def tearDown(self):
        self.window.close()

    def settle(self, window=None):
        window = window or self.window
        deadline = time.monotonic() + 5
        while window._busy and time.monotonic() < deadline:
            window.poll()
            app.processEvents()
            time.sleep(.01)
        self.assertFalse(window._busy)

    def test_one_install_button_runs_complete_pipeline_off_ui_thread_without_picker(self):
        self.window._token = 'private-mock-session'
        caller = threading.get_ident()
        workers = []
        def pipeline(product, token, settings, **options):
            workers.append(threading.get_ident())
            self.assertIs(product, self.product)
            self.assertEqual(token, 'private-mock-session')
            self.assertEqual(settings.download_directory, self.window.settings.download_directory)
            options['progress']('download', 6, 12, 'Downloading Phasis…')
            options['progress']('native_install', 0, None, 'Installing files…')
            return {'title': 'Phasis', 'version': '1.0', 'backend': 'native', 'activation': 'unverified',
                    'path': str(Path('verified.deb').resolve()), 'sha256': 'a' * 64}
        self.assertEqual(len(self.window.product_actions), 2)
        self.assertEqual(self.window.product_actions[0].text(), 'Install')
        self.assertTrue(self.window.product_actions[1].isEnabled())
        self.assertEqual(self.window.product_actions[1].text(), 'Install')
        with patch('tux_access.installation.install.install_product', side_effect=pipeline) as installer, \
             patch('tux_access.installation.install.installed_catalog', return_value=[]), \
             patch.object(self.window, '_show_download_picker') as picker, \
             patch.object(QtWidgets.QFileDialog, 'getExistingDirectory') as directory:
            self.window.product_actions[0].click()
            self.settle()
            installer.assert_called_once()
            picker.assert_not_called()
            directory.assert_not_called()
        self.assertNotEqual(workers[0], caller)
        self.assertNotIn('private-mock-session', self.window.status.text())
        self.assertIn('activation remains unverified', self.window.status.text())
        self.assertEqual(self.window._verified_files[str(Path('verified.deb').resolve())], 'a' * 64)
        self.assertEqual(self.window.products[1], self.other)

    def test_login_automatically_loads_catalog_and_keeps_credentials_transient(self):
        with patch('tux_access.auth.api.catalog', return_value={'products': [{'title': 'Phasis'}]}) as catalog, \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window._events.put(('login', {'access_token': 'private-token', 'refresh_token': 'private-refresh'}))
            self.window.poll()
            self.settle()
            catalog.assert_called_once_with('private-token')
        self.assertEqual(self.window.table.rowCount(), 1)
        visible = self.window.status.text() + self.window.account_status.text() + self.window.detail.toPlainText()
        self.assertNotIn('private-token', visible)
        self.assertNotIn('private-refresh', visible)

    def test_account_worker_expands_only_authorized_standalone_bundle_children_and_merges_aliases(self):
        from tux_access.catalog.applications import APPLICATIONS
        from tux_access.downloads.catalog import Artifact
        maschine = 'fccc863c-324f-4d79-af7e-b38c1f7488fe'
        guitar = 'e390057f-14b9-4e78-b033-3d7cc7e7767b'
        absynth = '00b224af-b357-4dfe-9929-414bbdf97d6f'
        ids = (maschine, guitar, absynth)
        artifacts = [Artifact(upid, APPLICATIONS[upid][0], '1.0', 'win', 'x86_64', 12,
                              'installer.zip', 'installer', '/private-installer-reference') for upid in ids]
        artifacts.append(Artifact('library-id', 'Library', '1.0', 'win', 'x86_64', 12,
                                  'library.zip', 'installer', '/private-library-reference'))
        payload = {'products': [{'title': 'Komplete bundle', 'upid': 'bundle-id'},
                                {'title': 'Maschine 2 Essentials Application for M32', 'upid': maschine},
                                {'title': 'Guitar Rig 6 Pro entitlement', 'upid': guitar}]}
        local = {'title': 'Maschine 2', 'backend': 'wine', 'status': 'Installed · activation unverified'}
        caller = threading.get_ident()
        def metadata(token):
            self.assertNotEqual(threading.get_ident(), caller)
            self.assertEqual(token, 'private-token')
            return artifacts
        self.artifacts_mock.side_effect = metadata
        self.window._token = 'private-token'
        with patch('tux_access.auth.api.catalog', return_value=payload), \
             patch('tux_access.installation.install.installed_catalog', return_value=[local]):
            self.window.account_catalog()
            self.settle()
        self.artifacts_mock.assert_called_once_with('private-token')
        self.assertEqual(self.window.artifacts, artifacts)
        self.assertEqual(len(self.window.products), 4)
        self.window.set_view('applications')
        self.assertEqual({self.window.table.item(row, 0).text() for row in range(self.window.table.rowCount())},
                         {'Maschine 2', 'Guitar Rig 6', 'Absynth 5'})
        matched = [product for product in self.window.products if product.get('upid') == maschine]
        self.assertEqual(len(matched), 1)
        self.assertTrue(self.window._installed_locally(matched[0]))
        self.assertEqual(matched[0]['_local_installation']['title'], 'Maschine 2')
        self.assertFalse(any(product.get('upid') in set(APPLICATIONS) - set(ids) for product in self.window.products))
        self.assertNotIn('private-installer-reference', repr(self.window.products))
        self.assertEqual(payload['products'][1]['title'], 'Maschine 2 Essentials Application for M32')

    def test_optional_artifact_failure_keeps_valid_catalog_with_private_safe_warning(self):
        self.window._token = 'private-token'
        self.artifacts_mock.side_effect = RuntimeError('private-token https://private.example/signed?key=secret')
        with patch('tux_access.auth.api.catalog', return_value={'products': [self.product]}), \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window.account_catalog()
            self.settle()
        self.assertEqual(self.window.products, [self.product])
        self.assertEqual(self.window.artifacts, [])
        self.assertIn('Application installer metadata is unavailable', self.window.status.text())
        self.assertIn('bundle applications may be missing', self.window.status.text())
        self.assertNotIn('secret', self.window.status.text())
        self.assertNotIn('private-token', self.window.status.text())

    def test_applications_filter_includes_verified_local_wine_and_preserves_ready_installed_views(self):
        application = {'title': 'Known app', 'upid': 'app-id', 'isApplication': True}
        local = {'title': 'Local app', 'backend': 'wine', 'status': 'Installed · activation unverified'}
        native = {'title': 'Phasis', 'backend': 'native', 'status': 'Installed · activation unverified'}
        self.window.products = [application, local, native, {'title': 'Sample library', 'upid': 'library-id'}]
        self.window.set_view('applications')
        self.assertEqual([self.window.table.item(row, 0).text() for row in range(self.window.table.rowCount())],
                         ['Known app', 'Local app'])
        self.window.set_view('installed')
        self.assertEqual(self.window.table.rowCount(), 2)
        self.window.set_view('supported')
        self.assertEqual(self.window.table.rowCount(), 0)
        self.window.set_view('all')
        self.assertEqual(self.window.table.rowCount(), 4)

    def test_native_transaction_disables_cancel_and_does_not_claim_completion_early(self):
        self.window._busy = True
        self.window._active_product = self.product
        self.window._installation_progress('download', 3, 12, 'Downloading…')
        self.window.poll()
        self.assertTrue(self.window.cancel_button.isEnabled())
        self.assertEqual(self.window.progress.value(), 25)
        self.window._installation_progress('native_install', 0, None, 'Waiting for system authentication…')
        self.window.poll()
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.assertTrue(self.window._busy)
        self.assertNotIn('files installed', self.window.status.text())
        self.window._busy = False

    def test_failure_exposes_retry_and_redacts_credentials_and_signed_url(self):
        self.window._token = 'private-token'
        attempts = []
        def fail(*args, **kwargs):
            attempts.append(1)
            raise RuntimeError('private-token https://example.test/file?signature=private')
        with patch('tux_access.installation.install.install_product', side_effect=fail):
            self.window.install_product(self.product)
            self.settle()
            self.assertIn('Operation failed', self.window.status.text())
            self.assertNotIn('private-token', self.window.status.text())
            self.assertNotIn('signature=', self.window.status.text())
            self.assertFalse(self.window.retry_button.isHidden())
            self.assertEqual(self.window.product_actions[0].text(), 'Retry')
            self.window.retry_operation()
            self.settle()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.window.table.item(0, 3).text(), 'Failed')

    def test_cancelled_pipeline_never_shows_installed_success(self):
        self.window._token = 'private-token'
        release = threading.Event()
        def cancel(*args, **kwargs):
            release.wait(3)
            raise DownloadCancelled('Download cancelled; partial file removed')
        with patch('tux_access.installation.install.install_product', side_effect=cancel):
            self.window.install_product(self.product)
            self.window.cancel_button.click()
            release.set()
            self.settle()
        self.assertEqual(self.window.table.item(0, 3).text(), 'Cancelled')
        self.assertNotIn('files installed', self.window.status.text())

    def test_busy_row_actions_remain_disabled_after_search(self):
        release = threading.Event()
        self.window._run('mock work', lambda: release.wait(3) and 'finished', 'error')
        try:
            self.assertTrue(all(not b.isEnabled() for b in self.window.product_actions))
            self.window.search.setText('Phasis')
            self.assertEqual(len(self.window.product_actions), 1)
            self.assertFalse(self.window.product_actions[0].isEnabled())
        finally:
            release.set()
            self.settle()
        self.assertTrue(self.window.product_actions[0].isEnabled())

    def test_success_merges_validated_local_status_without_losing_catalog_rows(self):
        native = {'title': 'PHASIS', 'version': '2.0', 'type': 'Native VST2', 'status': 'Installed · activation unverified'}
        self.window._events.put(('install', {'title': 'Phasis', 'version': '2.0', '_installed': [native]}))
        self.window.poll()
        self.assertEqual(len(self.window.products), 2)
        self.assertIs(self.window.products[0], self.product)
        self.assertEqual(self.window.products[0]['upid'], 'phasis-id')
        self.assertEqual(self.window.products[1], self.other)
        self.window.set_view('installed')
        self.assertEqual(self.window.table.rowCount(), 1)

    def test_advanced_manual_install_still_requires_verified_session_digest(self):
        with patch('tux_access.installation.native.arch.install_verified_vst') as installer:
            self.window._install_verified_path(str(Path('unverified.deb').resolve()))
            installer.assert_not_called()
        self.assertIn('checksum', self.window.status.text())

    def test_install_without_account_cannot_start_a_download(self):
        with patch('tux_access.installation.install.install_product') as installer:
            self.window.install_product(self.product)
            installer.assert_not_called()
        self.assertFalse(self.window._busy)
        self.assertIn('Sign in', self.window.status.text())

    def test_bad_settings_preserve_startup_with_visible_default_warning(self):
        from tux_access.settings import SettingsError
        with patch('tux_access.settings.load_settings', side_effect=SettingsError('Invalid configuration')), \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            window = Launcher()
        try:
            self.settle(window)
            self.assertEqual(window.settings, default_settings())
            self.assertIn('Defaults are active', window.status.text())
        finally:
            window.close()

    def test_catalog_export_excludes_private_and_signed_request_fields(self):
        self.window.products[0].update(access_token='private-token', url='https://example.test/?signature=private')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'catalog.json'
            with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(destination), '')):
                self.window.export_catalog()
            exported = destination.read_text(encoding='utf-8')
        self.assertIn('phasis-id', exported)
        self.assertNotIn('private-token', exported)
        self.assertNotIn('signature=', exported)

    def test_managed_installed_kontakt_has_launch_action_and_starts_off_ui_thread(self):
        self.window.products = [{'title': 'Kontakt 8', 'backend': 'wine', 'status': 'Installed · activation unverified'}]
        self.window.render()
        self.assertEqual(self.window.product_actions[0].text(), 'Launch')
        workers = []
        caller = threading.get_ident()
        class Process:
            pid = 123
        def launch(record):
            workers.append(threading.get_ident())
            return Process()
        with patch('tux_access.installation.wine.kontakt.WineManager') as manager:
            manager.return_value.launch_record.side_effect = launch
            self.window.product_actions[0].click()
            self.settle()
            manager.return_value.launch_record.assert_called_once_with(self.window.products[0])
        self.assertNotEqual(caller, workers[0])
        self.assertIn('process started', self.window.status.text())

    def test_wine_diagnostics_return_actionable_checks_without_claiming_success(self):
        with patch('tux_access.installation.wine.kontakt.WineManager') as manager:
            manager.return_value.diagnose.return_value = {'prefix': '/managed/kontakt', 'installation': {'status': 'not installed'},
                                                          'diagnostics': [{'status': 'error', 'message': 'Wine missing', 'action': 'Install Wine'}]}
            self.window.wine_diagnostics()
            self.settle()
        self.assertIn('Wine missing', self.window.detail.toPlainText())
        self.assertIn('Next step: Install Wine', self.window.detail.toPlainText())
        self.assertIn('activation: unverified', self.window.detail.toPlainText())

    def test_installed_maschine_launch_uses_its_own_manager_off_ui_thread(self):
        product = {'title': 'Maschine 2', 'version': '2.18.4', 'backend': 'wine', 'managed': True,
                   'status': 'Installed · activation unverified', 'prefix': '/known/maschine-2',
                   'executable': '/known/maschine-2/Maschine 2.exe', 'receipt': '/known/maschine-2/receipt'}
        self.window.products = [product]
        self.window.render()
        caller, workers = threading.get_ident(), []
        def launch(record):
            self.assertIs(record, product)
            workers.append(threading.get_ident())
            class Process:
                pid = 1234
            return Process()
        with patch('tux_access.installation.wine.maschine.MaschineManager') as manager, patch('tux_access.installation.wine.kontakt.WineManager') as kontakt:
            manager.return_value.launch_record.side_effect = launch
            self.assertEqual(self.window.product_actions[0].text(), 'Launch')
            self.window.product_actions[0].click()
            self.settle()
            kontakt.assert_not_called()
        self.assertNotEqual(caller, workers[0])
        self.assertIn('Maschine 2 process started', self.window.status.text())

    def test_installed_massive_launch_dispatches_registry_manager_with_canonical_record(self):
        record = {'title': 'Massive', 'version': '1.7.0', 'backend': 'wine', 'managed': True,
                  'status': 'Installed · activation unverified', 'prefix': '/known/massive',
                  'executable': '/known/massive/Massive.exe', 'receipt': '/known/massive/receipt'}
        product = {'title': 'Massive', 'upid': 'massive-id', 'backend': 'wine',
                   'status': 'Installed · activation unverified', '_local_installation': record}
        self.window.products = [product]
        self.window.render()
        self.assertEqual(self.window.product_actions[0].text(), 'Launch')
        caller, workers = threading.get_ident(), []
        def launch(passed):
            self.assertIs(passed, record)
            workers.append(threading.get_ident())
            class Process:
                pid = 4123
            return Process()
        with patch('tux_access.installation.wine.massive.MassiveManager') as manager, \
             patch('tux_access.installation.wine.kontakt.WineManager') as kontakt, \
             patch('tux_access.installation.wine.maschine.MaschineManager') as maschine:
            manager.return_value.launch_record.side_effect = launch
            self.window.product_actions[0].click()
            self.settle()
            manager.assert_called_once_with(self.window.settings)
            manager.return_value.launch_record.assert_called_once_with(record)
            kontakt.assert_not_called()
            maschine.assert_not_called()
        self.assertNotEqual(caller, workers[0])
        self.assertIn('Massive process started', self.window.status.text())
        self.assertNotIn('activation confirmed', self.window.status.text())

    def test_unknown_wine_profile_does_not_offer_or_dispatch_launch(self):
        record = {'title': 'Unknown standalone app', 'backend': 'wine', 'managed': True,
                  'status': 'Installed · activation unverified'}
        self.window.products = [record]
        self.window.render()
        self.assertNotEqual(self.window.product_actions[0].text(), 'Launch')
        self.assertFalse(self.window.product_actions[0].isEnabled())
        with patch.object(self.window, '_run') as worker, \
             patch('tux_access.installation.wine.kontakt.WineManager') as kontakt, \
             patch('tux_access.installation.wine.maschine.MaschineManager') as maschine, \
             patch('tux_access.installation.wine.massive.MassiveManager') as massive:
            self.window.launch_wine_product(record)
            worker.assert_not_called()
            kontakt.assert_not_called()
            maschine.assert_not_called()
            massive.assert_not_called()
        self.assertIn('No qualified application profile matches', self.window.status.text())
        self.assertFalse(self.window._busy)

    def test_startup_installed_file_scan_runs_off_ui_thread(self):
        caller = threading.get_ident()
        workers = []
        def scan(settings):
            workers.append(threading.get_ident())
            return [{'title': 'Kontakt 8', 'backend': 'wine', 'status': 'Installed · activation unverified'}]
        with patch('tux_access.settings.load_settings', return_value=default_settings()), \
             patch('tux_access.installation.install.installed_catalog', side_effect=scan):
            window = Launcher()
            self.settle(window)
        try:
            self.assertNotEqual(caller, workers[0])
            self.assertEqual(window.product_actions[0].text(), 'Launch')
        finally:
            window.close()

    def test_post_commit_scan_failure_does_not_prompt_reinstallation(self):
        self.window._token = 'private-token'
        with patch('tux_access.installation.install.install_product', return_value={'title': 'Phasis', 'version': '1.0', 'backend': 'native'}), \
             patch('tux_access.installation.install.installed_catalog', side_effect=OSError('Local check unavailable')):
            self.window.install_product(self.product)
            self.settle()
        self.assertIn('files installed', self.window.status.text())
        self.assertIn('catalog check needs attention', self.window.status.text())
        self.assertEqual(self.window.product_actions[0].text(), 'Installed')
        self.assertFalse(self.window.product_actions[0].isEnabled())
        self.assertTrue(self.window.retry_button.isHidden())

    def test_small_window_action_labels_fit_and_installed_rows_are_not_counted_ready(self):
        self.window.products = [
            {'title': 'Phasis', 'source': 'native-install', 'status': 'Installed · activation unverified'},
            {'title': 'Kontakt 8', 'backend': 'wine', 'status': 'Installed · activation unverified'},
            {'title': 'Reaktor 6'},
            self.other,
            {'title': 'Maschine 3', 'upid': 'maschine-id'},
            {'title': 'Additional product', 'upid': 'additional-id'},
        ]
        self.window.resize(900, 650)
        self.window.render()
        self.window.show()
        for _ in range(3):
            app.processEvents()
        self.assertEqual([button.text() for button in self.window.product_actions], ['Installed', 'Launch', 'Install', 'Install', 'Install', 'Install'])
        self.assertIn('1 ready to install', self.window.library_summary.text())
        for row, button in enumerate(self.window.product_actions):
            cell = self.window.table.cellWidget(row, 4)
            cell.layout().activate()
            self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 32)
            margins = cell.layout().contentsMargins()
            inside_cell = QtCore.QRect(button.mapTo(cell, QtCore.QPoint()), button.size())
            self.assertGreaterEqual(inside_cell.left(), margins.left())
            self.assertLessEqual(inside_cell.right(), cell.width() - margins.right() - 1)
            inside_viewport = QtCore.QRect(button.mapTo(self.window.table.viewport(), QtCore.QPoint()), button.size())
            viewport = self.window.table.viewport().rect()
            self.assertGreaterEqual(inside_viewport.left(), viewport.left())
            self.assertLessEqual(inside_viewport.right(), viewport.right())
            if 0 <= inside_viewport.top() and inside_viewport.bottom() <= viewport.bottom():
                self.assertTrue(viewport.contains(inside_viewport))
        self.assertGreaterEqual(self.window.cancel_button.height(), 38)
        self.assertTrue(self.window.table.isColumnHidden(2))

    def test_embedded_settings_scroll_contents_render_dark(self):
        self.window.show_settings()
        self.window.resize(900, 650)
        self.window.show()
        for _ in range(3):
            app.processEvents()
        areas = self.window._settings_page.findChildren(QtWidgets.QScrollArea)
        self.assertEqual(len(areas), 2)
        for area in areas:
            area.widget().ensurePolished()
            rendered = area.widget().grab().toImage()
            self.assertLess(rendered.pixelColor(2, 2).lightness(), 80)
        self.assertGreaterEqual(self.window.cancel_button.height(), 38)

    def test_filter_and_reordering_preserve_product_identity_and_clear_hidden_details(self):
        kontakt = {'title': 'Kontakt 8', 'upid': 'kontakt-id'}
        maschine = {'title': 'Maschine 3', 'upid': 'maschine-id'}
        self.window.products = [self.product, kontakt, maschine]
        self.window.render()
        self.window.table.setCurrentCell(1, 0)
        self.window.table.selectRow(1)
        self.window.details()
        self.assertIs(self.window._selected_product(), kontakt)
        self.window.products = [maschine, self.product, kontakt]
        self.window.render()
        self.assertIs(self.window._selected_product(), kontakt)
        self.window.search.setText('Kontakt')
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertIs(self.window._selected_product(), kontakt)
        self.assertIn('Product: Kontakt 8', self.window.detail.toPlainText())
        self.window.search.setText('Maschine')
        self.assertIsNone(self.window._selected_product())
        self.assertNotIn('Product: Kontakt 8', self.window.detail.toPlainText())
        self.window.search.clear()
        self.assertIs(self.window._selected_product(), kontakt)
        self.assertEqual(self.window.table.currentRow(), 2)

    def test_settings_are_embedded_and_cancel_discards_unsaved_paths(self):
        original = self.window.settings
        with patch.object(QtWidgets.QDialog, 'exec') as modal, patch('tux_access.settings.save_settings') as save:
            self.window.show_settings()
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            self.assertFalse(isinstance(self.window._settings_page, QtWidgets.QDialog))
            self.window._settings_fields['download_directory'].setText('/changed/downloads')
            self.window.settings_cancel_button.click()
            self.assertIs(self.window.pages.currentWidget(), self.window.library_page)
            self.assertEqual(self.window.settings, original)
            self.window.show_settings()
            self.assertEqual(self.window._settings_fields['download_directory'].text(), str(original.download_directory))
            modal.assert_not_called()
            save.assert_not_called()

    def test_settings_default_to_installation_unless_advanced_is_requested(self):
        from dataclasses import replace
        self.window.settings = replace(self.window.settings, manual_mode=False)
        self.window.show_settings()
        tabs = self.window._settings_page.findChild(QtWidgets.QTabWidget)
        self.assertEqual(tabs.currentIndex(), 0)
        self.window.set_view('all')
        self.window.show_settings(product=self.other, advanced=True)
        tabs = self.window._settings_page.findChild(QtWidgets.QTabWidget)
        self.assertEqual(tabs.currentIndex(), 1)
        self.window.set_view('all')
        self.window.settings = replace(self.window.settings, manual_mode=True)
        self.window.show_settings()
        tabs = self.window._settings_page.findChild(QtWidgets.QTabWidget)
        self.assertEqual(tabs.currentIndex(), 1)

    def test_about_is_embedded_below_settings_and_preserves_library_session_and_artwork(self):
        self.window._token = 'private-token'
        self.window._refresh_token = 'private-refresh'
        self.window._profile = {'given_name': 'Private'}
        artifacts = [object()]
        self.window.artifacts = artifacts
        products = self.window.products
        artwork = self.window.sidebar_art.source_path
        sidebar_layout = self.window.settings_button.parentWidget().layout()
        self.assertEqual(sidebar_layout.indexOf(self.window.about_button),
                         sidebar_layout.indexOf(self.window.settings_button) + 1)
        with patch.object(QtWidgets.QDialog, 'exec') as modal, \
             patch('tux_access.ui.main_window.QtGui.QDesktopServices.openUrl') as browser:
            self.window.about_button.click()
            page = self.window._about_page
            self.assertIs(self.window.pages.currentWidget(), page)
            self.assertFalse(isinstance(page, QtWidgets.QDialog))
            self.assertTrue(self.window.about_button.isChecked())
            self.assertFalse(self.window.settings_button.isChecked())
            text = '\n'.join(label.text() for label in page.findChildren(QtWidgets.QLabel))
            self.assertIn('independent, unofficial', text)
            self.assertIn('Not affiliated with, endorsed by, or supported by Native Instruments.', text)
            self.assertIn('MIT license', text)
            self.assertIn('subject to its own licenses', text)
            self.assertIn('0.9.2', text)
            self.assertIn('prototype', text.casefold())
            self.assertNotIn('200', text)
            self.assertNotIn('private-token', text)
            links = [label for label in page.findChildren(QtWidgets.QLabel) if label.openExternalLinks()]
            self.assertEqual(len(links), 1)
            self.assertIn('https://community.native-instruments.com/discussion/355/petition-for-linux/p2', links[0].text())
            self.assertIn('https://community.native-instruments.com/discussion/5666/native-instruments-products-natively-on-linux/p2', links[0].text())
            self.window.settings_button.click()
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            self.assertFalse(self.window.about_button.isChecked())
            self.window.about_button.click()
            self.assertIs(self.window.pages.currentWidget(), page)
            self.window.set_view('all')
            self.assertIs(self.window.pages.currentWidget(), self.window.library_page)
            self.assertFalse(self.window.about_button.isChecked())
            modal.assert_not_called()
            browser.assert_not_called()
        self.assertIs(self.window.products, products)
        self.assertIs(self.window.artifacts, artifacts)
        self.assertEqual(self.window._token, 'private-token')
        self.assertEqual(self.window._refresh_token, 'private-refresh')
        self.assertEqual(self.window._profile, {'given_name': 'Private'})
        self.assertEqual(self.window.sidebar_art.source_path, artwork)

    def test_about_keeps_running_worker_progress_and_cancel_available(self):
        started, release = threading.Event(), threading.Event()
        def operation():
            self.window._events.put(('progress', (3, 10)))
            started.set()
            release.wait(3)
            return {'path': str(Path('verified-about-test.zip').resolve()), 'sha256': 'a' * 64}
        self.window._token = 'private-token'
        self.window._run('Download is running…', operation, 'download', download=True)
        try:
            self.assertTrue(started.wait(1))
            self.window.about_button.click()
            self.window.poll()
            self.assertTrue(self.window._busy)
            self.assertFalse(self.window._cancel.is_set())
            self.assertTrue(self.window.cancel_button.isEnabled())
            self.assertEqual(self.window.progress.value(), 30)
            self.assertEqual(self.window.status.text(), 'Download is running…')
            self.assertIs(self.window.pages.currentWidget(), self.window._about_page)
        finally:
            release.set()
            self.settle()
        self.assertIs(self.window.pages.currentWidget(), self.window._about_page)
        self.assertEqual(self.window._token, 'private-token')
        self.assertIn('Verified download saved', self.window.status.text())

    def test_embedded_settings_save_persists_options_and_returns_to_library(self):
        # Page construction captures the save adapter in its callback. Patch
        # before constructing it so this fixture never writes real settings.
        with tempfile.TemporaryDirectory() as directory, \
             patch('tux_access.settings.save_settings') as save, \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window.show_settings()
            chosen = Path(directory) / 'chosen-downloads'
            self.window._settings_fields['download_directory'].setText(str(chosen))
            self.window.settings_save_button.click()
            self.settle()
            save.assert_called_once()
            self.assertEqual(save.call_args.args[0].download_directory, chosen)
            self.assertEqual(self.window.settings.download_directory, chosen)
        self.assertIs(self.window.pages.currentWidget(), self.window.library_page)
        self.assertIsNone(QtWidgets.QApplication.activeModalWidget())

    def test_profile_initial_is_fetched_on_worker_and_signout_clears_private_state(self):
        workers = []
        caller = threading.get_ident()
        def profile(token):
            workers.append(threading.get_ident())
            return {'name': 'Private Person', 'given_name': 'Gwen', 'picture': 'https://private.example/image', 'email': 'private@example.test'}
        local = {'title': 'Kontakt 8', 'backend': 'wine', 'status': 'Installed · activation unverified'}
        with patch('tux_access.auth.api.catalog', return_value={'products': [{'title': 'Maschine 3', 'upid': 'maschine-id'}]}), \
             patch('tux_access.auth.profile.profile', side_effect=profile), \
             patch('tux_access.installation.install.installed_catalog', return_value=[local]):
            self.window._events.put(('login', {'access_token': 'private-token', 'refresh_token': 'private-refresh'}))
            self.window.poll()
            self.settle()
        self.assertNotEqual(caller, workers[0])
        self.assertEqual(self.window.sign_in_button.text(), 'G')
        self.assertEqual([action.text() for action in self.window.account_menu.actions()], ['Switch account', 'Sign out'])
        self.assertNotIn('picture', self.window._profile)
        self.assertNotIn('email', self.window._profile)
        self.window._verified_files['/private/file'] = 'a' * 64
        self.window._verified_artifacts['/private/file'] = object()
        self.window.artifacts = [object()]
        self.window.sign_out_action.trigger()
        self.assertIsNone(self.window._token)
        self.assertIsNone(self.window._refresh_token)
        self.assertEqual(self.window._profile, {})
        self.assertEqual(self.window._verified_files, {})
        self.assertEqual(self.window._verified_artifacts, {})
        self.assertEqual(self.window.artifacts, [])
        self.assertEqual(self.window.products, [local])
        self.assertEqual(self.window.sign_in_button.text(), 'Sign in')
        visible = self.window.status.text() + self.window.account_status.text() + self.window.detail.toPlainText()
        self.assertNotIn('Private Person', visible)
        self.assertNotIn('private-token', visible)
        self.assertNotIn('Maschine 3', visible)

    def test_profile_failure_does_not_discard_account_catalog(self):
        self.window._token = 'private-token'
        with patch('tux_access.auth.api.catalog', return_value={'products': [self.product]}), \
             patch('tux_access.auth.profile.profile', side_effect=RuntimeError('Private profile unavailable')), \
             patch('tux_access.installation.install.installed_catalog', return_value=[]):
            self.window.account_catalog()
            self.settle()
        self.assertEqual(self.window.products, [self.product])
        self.assertEqual(self.window.sign_in_button.text(), 'A')
        self.assertNotIn('Private profile unavailable', self.window.status.text())

    def test_maschine_reports_not_available_yet_without_starting_installer(self):
        product = {'title': 'Maschine 3', 'upid': 'maschine-id'}
        self.window.products = [product]
        self.window.render()
        self.window.table.setCurrentCell(0, 0)
        self.window.details()
        self.assertIn('Maschine 3 installation is not available yet', self.window.detail.toPlainText())
        with patch('tux_access.installation.install.install_product') as installer:
            self.window.product_actions[0].click()
            installer.assert_not_called()
        self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
        self.assertIs(self.window._options_product, product)
        self.assertIn('Maschine 3 installation is not available yet', self.window.status.text())

    def test_explicit_advanced_options_only_download_selected_artifact(self):
        from tux_access.downloads.catalog import Artifact
        product = {'title': 'Maschine 3', 'upid': 'maschine-id'}
        selected = Artifact('maschine-id', 'Maschine 3', '3.0', 'win', 'x86_64', 12, 'Maschine.zip', 'installer', '/private/artifact')
        other = Artifact('other-id', 'Other', '1.0', 'win', 'x86_64', 12, 'Other.zip', 'installer', '/private/other')
        self.window.products = [product]
        self.window._token = 'private-token'
        self.window.render()
        self.assertTrue(self.window.product_actions[0].isEnabled())
        self.assertEqual(self.window.product_actions[0].text(), 'Install')
        with patch('tux_access.downloads.catalog.available_artifacts', return_value=[selected, other]), \
             patch.object(QtWidgets.QDialog, 'exec') as modal, \
             patch('tux_access.installation.install.install_product') as installer:
            self.window.open_install_options(product)
            self.settle()
            self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)
            self.assertIs(self.window._options_product, product)
            self.assertEqual(self.window.inline_installer_table.rowCount(), 1)
            self.assertEqual(self.window._inline_artifacts, [selected])
            self.window.inline_installer_table.setCurrentCell(0, 0)
            with patch.object(self.window, 'download_artifact') as download:
                self.window.inline_download_button.click()
                download.assert_called_once_with(selected, str(self.window.settings.download_directory))
            modal.assert_not_called()
            installer.assert_not_called()

    def test_inline_choices_prefer_platform_then_latest_numeric_version_without_automatic_download(self):
        from dataclasses import replace
        from tux_access.downloads.catalog import Artifact
        product = {'title': 'Massive', 'upid': 'massive-id'}
        old_pc = Artifact('massive-id', 'Massive', '1.5.12', 'pc', 'x86_64', 12, 'old.zip', 'installer', '/private/old')
        latest_pc = replace(old_pc, version='1.7.0', platform='win', target_file='latest.zip')
        mac = replace(old_pc, version='9.0', platform='mac', target_file='mac.zip')
        linux = replace(old_pc, version='1.6.0', platform='linux', target_file='linux.deb')
        self.window.products = [product]
        self.window._token = 'private-token'
        self.artifacts_mock.return_value = [mac, old_pc, latest_pc, linux]
        for prefer_native, expected in ((False, [latest_pc, old_pc, linux, mac]),
                                        (True, [linux, latest_pc, old_pc, mac])):
            with self.subTest(prefer_native=prefer_native), \
                 patch.object(self.window, 'download_artifact') as download, \
                 patch('tux_access.installation.install.install_product') as install, \
                 patch.object(QtWidgets.QDialog, 'exec') as modal:
                self.window.set_view('all')
                self.window.settings = replace(self.window.settings, prefer_native=prefer_native)
                self.window.open_install_options(product)
                self.settle()
                self.assertEqual(self.window._inline_artifacts, expected)
                self.assertEqual(self.window.inline_installer_table.currentRow(), 0)
                self.assertEqual(self.window.inline_installer_table.item(0, 0).text(), expected[0].version)
                self.assertGreaterEqual(self.window.inline_installer_table.minimumHeight(), 240)
                download.assert_not_called()
                install.assert_not_called()
                modal.assert_not_called()
                self.window.inline_download_button.click()
                download.assert_called_once_with(expected[0], str(self.window.settings.download_directory))

    def test_selected_installed_native_has_manual_options_in_details(self):
        product = {'title': 'Phasis', 'source': 'native-install', 'status': 'Installed · activation unverified'}
        self.window.products = [product]
        self.window.render()
        self.window.table.setCurrentCell(0, 0)
        self.window.details()
        self.assertEqual(self.window.product_actions[0].text(), 'Installed')
        self.assertFalse(self.window.product_actions[0].isEnabled())
        self.assertTrue(self.window.product_options_button.isEnabled())
        self.window.product_options_button.click()
        self.assertIs(self.window._options_product, product)
        self.assertIs(self.window.pages.currentWidget(), self.window._settings_page)

    def test_alias_account_product_launches_exact_verified_local_record(self):
        product = {'title': 'Kontakt 8 Player', 'upid': 'player-id'}
        record = {'title': 'Kontakt 8', 'version': '8.9.0', 'backend': 'wine', 'managed': False,
                  'status': 'Installed · activation unverified', 'source': 'verified legacy experiment',
                  'prefix': '/known/legacy', 'executable': '/known/legacy/Kontakt.exe', 'receipt': '/known/receipt'}
        self.window.products = [product]
        self.window._merge_installed([record])
        self.window.render()
        with patch('tux_access.installation.wine.kontakt.WineManager') as manager:
            manager.return_value.launch_record.return_value.pid = 123
            self.window.product_actions[0].click()
            self.settle()
        passed = manager.return_value.launch_record.call_args.args[0]
        self.assertEqual(passed['title'], 'Kontakt 8')
        self.assertEqual(passed['prefix'], '/known/legacy')
        self.assertIs(passed['managed'], False)
        self.assertEqual(product['title'], 'Kontakt 8 Player')

    def test_switch_account_requests_fresh_authorization_and_cancel_keeps_session(self):
        self.window._token = 'private-existing-token'
        self.window._update_account_button()
        from tux_access.auth.browser import browser_login_banner
        with tempfile.TemporaryDirectory() as directory:
            login = browser_login_banner(self.window, opener=lambda url: True,
                                         prepare_handler=lambda: None, runtime_dir=Path(directory))
            with patch('tux_access.auth.login.login_banner', return_value=login) as factory:
                self.window.switch_account_action.trigger()
                factory.assert_called_once_with(self.window, force_login=True)
            login.cancel_button.click()
        self.assertEqual(self.window._token, 'private-existing-token')
        self.assertIsNone(login.code)
        self.assertIsNone(login.verifier)
        self.assertIsNone(self.window._login_banner)

    @unittest.skipUnless(os.name == 'posix', 'Private Linux browser callback required')
    def test_signin_banner_is_inline_nonmodal_and_duplicate_click_keeps_one_receiver(self):
        from tux_access.auth.browser import browser_login_banner
        with tempfile.TemporaryDirectory() as directory:
            opened = []
            banner = browser_login_banner(self.window, opener=lambda url: opened.append(url) or True,
                                          prepare_handler=lambda: None, runtime_dir=Path(directory))
            self.window.show()
            with patch('tux_access.auth.login.login_banner', return_value=banner), patch.object(QtWidgets.QDialog, 'exec') as modal:
                self.window.sign_in()
                self.window.sign_in()
                self.assertIs(self.window._login_banner, banner)
                self.assertIs(banner.parentWidget(), self.window.sign_in_area)
                self.assertFalse(banner.isWindow())
                self.assertEqual(len(opened), 1)
                modal.assert_not_called()
                self.window.search.setText('Unsupported')
                self.assertFalse(self.window.product_actions[0].isEnabled())
                banner.cancel_button.click()
                self.assertTrue(self.window.sign_in_area.isHidden())
                self.assertTrue(self.window.product_actions[0].isEnabled())
            self.assertFalse((Path(directory) / 'native-access-linux-oauth/callback.sock').exists())

    @unittest.skipUnless(os.name == 'posix', 'Private Linux browser callback required')
    def test_banner_callback_exchanges_off_ui_thread_then_refreshes_catalog(self):
        from tux_access.auth.browser import browser_login_banner
        from tux_access.auth.callback import forward_callback
        from tux_access.auth.oauth import APP_REDIRECT
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            banner = browser_login_banner(self.window, opener=lambda url: True,
                                          prepare_handler=lambda: None, runtime_dir=Path(directory))
            caller = threading.get_ident()
            def exchange(*args):
                self.assertNotEqual(threading.get_ident(), caller)
                self.assertEqual(args[0], 'mock-code')
                return {'access_token': 'private-new-token'}
            with patch('tux_access.auth.login.login_banner', return_value=banner), \
                 patch('tux_access.auth.oauth.exchange_code', side_effect=exchange), \
                 patch('tux_access.auth.api.catalog', return_value={'products': [{'title': 'Phasis'}]}), \
                 patch('tux_access.installation.install.installed_catalog', return_value=[]):
                self.window.sign_in()
                uri = APP_REDIRECT + '?' + urlencode({'code': 'mock-code', 'state': banner.state})
                self.assertTrue(forward_callback(uri, Path(directory)))
                banner.poll_callbacks()
                self.settle()
            self.assertEqual(self.window._token, 'private-new-token')
            self.assertEqual(self.window.table.rowCount(), 1)
            self.assertIsNone(banner.code)
            self.assertIsNone(banner.verifier)
            self.assertTrue(self.window.sign_in_area.isHidden())

    def test_close_during_browser_wait_releases_receiver_without_hanging(self):
        from tux_access.auth.browser import browser_login_banner
        with tempfile.TemporaryDirectory() as directory:
            banner = browser_login_banner(self.window, opener=lambda url: True,
                                          prepare_handler=lambda: None, runtime_dir=Path(directory))
            with patch('tux_access.auth.login.login_banner', return_value=banner):
                self.window.sign_in()
            self.window.close()
            self.assertIsNone(self.window._login_banner)
            self.assertIsNone(banner.verifier)
            self.assertFalse((Path(directory) / 'native-access-linux-oauth/callback.sock').exists())


if __name__ == '__main__':
    unittest.main()
