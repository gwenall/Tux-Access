import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import time
import unittest
from unittest.mock import patch
try:
    from PySide6 import QtWidgets
except ImportError:
    raise unittest.SkipTest('Qt desktop extra is not installed')
from qt_launcher import Launcher

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class QtWorkerTests(unittest.TestCase):
    def setUp(self):
        self.window = Launcher()

    def tearDown(self):
        self.window.close()

    def settle(self):
        deadline = time.monotonic() + 3
        while self.window._busy and time.monotonic() < deadline:
            app.processEvents()
            self.window.poll()
            time.sleep(.01)
        self.assertFalse(self.window._busy)

    def test_connection_and_account_worker(self):
        with patch('qt_launcher.daemon_snapshot', return_value=([{'title': 'Mock product', 'installed': True}],
                    {'major': 1, 'minor': 32, 'micro': 0}, 'mock-session')):
            self.window.connect_daemon()
            self.settle()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertNotIn('mock-session', self.window.status.text())
        with patch('account_api.catalog', return_value={'products': [{'title': 'Account mock'}]}) as adapter:
            self.window.account_catalog()
            self.settle()
            adapter.assert_called_once_with('mock-session')
        self.assertEqual(self.window.table.item(0, 0).text(), 'Account mock')

    def test_error_and_cancel_worker(self):
        def operation():
            self.window._events.put(('progress', (25, 100)))
            deadline = time.monotonic() + 2
            while not self.window._cancel.is_set() and time.monotonic() < deadline:
                time.sleep(.01)
            raise RuntimeError('Download cancelled')
        self.window._run('mock download', operation, 'download', download=True)
        self.assertTrue(self.window.cancel_button.isEnabled())
        self.window.cancel_button.click()
        self.settle()
        self.assertEqual(self.window.progress.value(), 25)
        self.assertIn('cancelled', self.window.status.text())
        self.assertTrue(all(button.isEnabled() for button in self.window.actions))


if __name__ == '__main__':
    unittest.main()
