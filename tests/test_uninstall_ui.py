"""Uninstall buttons and honest inventory transitions; no files are removed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time
import unittest
from unittest.mock import patch
try:
    from PySide6 import QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')
from app_settings import default_settings
from download_manager import DownloadCancelled
from qt_launcher import Launcher

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class UninstallUiTests(unittest.TestCase):
    def setUp(self):
        with patch('app_settings.load_settings', return_value=default_settings()), \
             patch('install_coordinator.installed_catalog', return_value=[]):
            self.window = Launcher()
        self.window._timer.stop()
        self.settle()
        self.record = {'title': 'Maschine 2', 'version': '2.18.4', 'backend': 'wine', 'managed': True,
                       'source': 'managed installation', 'status': 'Installed · activation unverified',
                       'prefix': '/known/maschine', 'executable': '/known/maschine/Maschine.exe', 'receipt': '/known/receipt'}
        self.account = {'title': 'Maschine 2', 'upid': 'maschine-id', 'type': 'Application'}
        self.window._load_account_rows([self.account, {'title': 'Another account product', 'upid': 'other-id'}])
        self.window._merge_installed([self.record])
        self.window.render()
        self.window.table.setCurrentCell(0, 0)
        self.window.table.selectRow(0)
        self.window.details()

    def tearDown(self):
        self.window.close()

    def settle(self):
        deadline = time.monotonic() + 5
        while self.window._busy and time.monotonic() < deadline:
            self.window.poll()
            app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window._busy)

    def result(self, installed=()):
        return {'title': 'Maschine 2', 'version': '2.18.4', 'backend': 'wine', 'status': 'uninstalled',
                'retained_directory': '/known/retained-data/maschine-dated', '_installed': list(installed)}

    def test_uninstall_requires_inline_confirmation_and_cancel_does_not_remove_files(self):
        self.assertEqual(self.window.product_actions[0].text(), 'Launch')
        self.assertTrue(self.window.uninstall_button.isEnabled())
        with patch('removal_coordinator.uninstall_product') as remove, patch.object(QtWidgets.QDialog, 'exec') as modal:
            self.window.uninstall_button.click()
            self.assertFalse(self.window.uninstall_panel.isHidden())
            self.assertIn('Saved projects, content and settings will be retained', self.window.uninstall_notice.text())
            remove.assert_not_called()
            self.window.uninstall_cancel_button.click()
            self.assertTrue(self.window.uninstall_panel.isHidden())
            remove.assert_not_called()
            modal.assert_not_called()
        self.assertEqual(self.window.product_actions[0].text(), 'Launch')

    def test_confirm_removes_canonical_record_on_worker_and_account_row_returns_to_install(self):
        caller = threading.get_ident()
        workers = []
        def remove(record, settings, **options):
            workers.append(threading.get_ident())
            self.assertEqual(record['prefix'], '/known/maschine')
            self.assertNotIn('upid', record)
            options['progress']({'stage': 'verifying_removal', 'current': 1, 'total': 2, 'message': 'Checking files'})
            options['progress']({'stage': 'removing', 'message': 'Removing app files'})
            return self.result()
        with patch('removal_coordinator.uninstall_product', side_effect=remove) as remover:
            self.window.uninstall_button.click()
            self.window.uninstall_confirm_button.click()
            self.settle()
            remover.assert_called_once()
        self.assertNotEqual(workers[0], caller)
        product = self.window.products[0]
        self.assertEqual(product['upid'], 'maschine-id')
        self.assertEqual(product['status'], 'Not installed')
        for field in ('prefix', 'backend', 'receipt', 'managed', '_local_installation', 'installedVersion'):
            self.assertNotIn(field, product)
        self.assertEqual(self.window.product_actions[0].text(), 'Install')
        self.assertEqual(self.window.products[1]['upid'], 'other-id')
        self.assertEqual(self.window._product_states, {})
        self.assertIn('/known/retained-data/maschine-dated', self.window.status.text())
        self.assertFalse(self.window.uninstall_button.isEnabled())

    def test_purely_local_removed_row_disappears(self):
        self.window._account_records = []
        self.window.products = [dict(self.record)]
        self.window.render()
        self.window.table.setCurrentCell(0, 0)
        self.window.details()
        with patch('removal_coordinator.uninstall_product', return_value=self.result()):
            self.window.uninstall_button.click()
            self.window.uninstall_confirm_button.click()
            self.settle()
        self.assertEqual(self.window.products, [])
        self.assertEqual(self.window.table.rowCount(), 0)

    def test_legacy_copy_remains_launchable_and_cannot_be_uninstalled(self):
        managed = {**self.record, 'title': 'Kontakt 8', 'version': '8.9.0', 'prefix': '/known/kontakt'}
        legacy = {**managed, 'managed': False, 'source': 'verified legacy experiment', 'prefix': '/known/legacy'}
        self.window._load_account_rows([{'title': 'Kontakt 8', 'upid': 'kontakt-id'}])
        self.window._merge_installed([managed])
        self.window.render()
        self.window.table.setCurrentCell(0, 0)
        self.window.details()
        result = {**self.result([legacy]), 'title': 'Kontakt 8', 'version': '8.9.0'}
        with patch('removal_coordinator.uninstall_product', return_value=result):
            self.window.uninstall_button.click()
            self.window.uninstall_confirm_button.click()
            self.settle()
        self.assertEqual(self.window.product_actions[0].text(), 'Launch')
        self.assertFalse(self.window.uninstall_button.isEnabled())
        self.assertIn('Another verified installation remains', self.window.status.text())
        with patch('removal_coordinator.uninstall_product') as remove:
            self.window.request_uninstall(self.window.products[0])
            remove.assert_not_called()
            self.assertTrue(self.window.uninstall_panel.isHidden())

    def test_verification_can_cancel_but_removing_stage_disables_cancel(self):
        self.window._busy = True
        self.window._active_product = self.window.products[0]
        self.window._installation_progress('verifying_removal', 1, 2, 'Checking files')
        self.window.poll()
        self.assertTrue(self.window.cancel_button.isEnabled())
        self.window._installation_progress('removing', 0, 0, 'Removing app files')
        self.window.poll()
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.assertTrue(self.window._busy)
        self.window._busy = False

    def test_cancelled_or_failed_removal_refreshes_actual_remaining_files(self):
        for error in (DownloadCancelled('Removal cancelled'), RuntimeError('Changed file preserved')):
            with self.subTest(error=type(error).__name__), \
                 patch('removal_coordinator.uninstall_product', side_effect=error), \
                 patch('install_coordinator.installed_catalog', return_value=[self.record]):
                self.window.request_uninstall(self.window.products[0])
                self.window.uninstall_confirm_button.click()
                self.settle()
                self.assertEqual(self.window.product_actions[0].text(), 'Launch')
                self.assertNotIn('app files uninstalled', self.window.status.text())
                self.assertTrue(self.window.uninstall_button.isEnabled())
                self.assertFalse(self.window.retry_button.isHidden())

    def test_scan_failure_does_not_claim_zero_installed_or_offer_immediate_reinstall(self):
        result = self.result()
        result.update(_installed=None, _scan_warning='Refresh the library to check other copies.')
        with patch('removal_coordinator.uninstall_product', return_value=result):
            self.window.uninstall_button.click()
            self.window.uninstall_confirm_button.click()
            self.settle()
        self.assertEqual(self.window.product_actions[0].text(), 'Check state')
        self.assertFalse(self.window.product_actions[0].isEnabled())
        self.assertIn('Refresh the library', self.window.status.text())
        with patch('install_coordinator.installed_catalog', return_value=[]):
            self.window.account_catalog()  # Offline Refresh checks local files.
            self.settle()
        self.assertEqual(self.window.product_actions[0].text(), 'Install')


if __name__ == '__main__':
    unittest.main()
