import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from wine_display import DisplayError, ensure_display, _authority, _cookie, _slot


class Child:
    def __init__(self, argv, **options):
        self.argv, self.options = argv, options
        self.pid = 54321
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class ExistingDisplayTests(unittest.TestCase):
    def test_existing_desktop_is_preserved_without_spawning_or_reading_runtime(self):
        environment = {'DISPLAY': ':0', 'XAUTHORITY': '/desktop/authority', 'WAYLAND_DISPLAY': 'wayland-0'}
        with patch('wine_display.subprocess.Popen', side_effect=AssertionError('no new server')), \
             patch('wine_display._runtime', side_effect=AssertionError('no private runtime needed')):
            self.assertEqual(ensure_display(environment), {'DISPLAY': ':0', 'XAUTHORITY': '/desktop/authority'})


@unittest.skipUnless(os.name == 'posix', 'Linux user-owned runtime and sockets')
class ManagedDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.wayland = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.wayland.bind(str(self.root / 'wayland-0'))
        self.environment = {'XDG_RUNTIME_DIR': str(self.root), 'WAYLAND_DISPLAY': 'wayland-0'}
        self.children = []

    def tearDown(self):
        self.wayland.close()
        self.temporary.cleanup()

    def create_child(self, argv, **options):
        child = Child(argv, **options)
        self.children.append(child)
        return child

    def identity(self, pid):
        self.assertEqual(pid, 54321)
        return '987654', self.children[-1].argv

    def test_creates_private_authenticated_server_then_reuses_exact_owned_identity(self):
        with patch('wine_display.shutil.which', return_value='/usr/bin/Xwayland'), \
             patch('wine_display._slot', return_value=9), \
             patch('wine_display.subprocess.Popen', side_effect=self.create_child), \
             patch('wine_display._identity', side_effect=self.identity), \
             patch('wine_display._authenticated', return_value=True):
            first = ensure_display(self.environment)
            second = ensure_display(self.environment)
        self.assertEqual(first, second)
        self.assertEqual(len(self.children), 1)
        self.assertFalse(self.children[0].terminated)
        self.assertEqual(first['DISPLAY'], ':9')
        auth = Path(first['XAUTHORITY'])
        cookie = _cookie(auth)
        state = json.loads((auth.parent / 'display.json').read_text())
        self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
        self.assertEqual(auth.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(cookie.hex(), json.dumps(state))
        self.assertNotIn(cookie.hex(), repr(self.children[0].argv))
        self.assertIn('-nolisten', self.children[0].argv)
        self.assertIn('tcp', self.children[0].argv)
        self.assertEqual(self.children[0].options['stderr'], -3)  # DEVNULL

    def test_readiness_timeout_stops_only_new_child_and_removes_its_authority(self):
        with patch('wine_display.shutil.which', return_value='/usr/bin/Xwayland'), \
             patch('wine_display._slot', return_value=9), \
             patch('wine_display.subprocess.Popen', side_effect=self.create_child), \
             patch('wine_display._authenticated', return_value=False):
            with self.assertRaisesRegex(DisplayError, 'did not become ready'):
                ensure_display(self.environment, timeout=0.05)
        self.assertTrue(self.children[0].terminated)
        private = self.root / 'native-access-linux-wine'
        self.assertFalse((private / 'display.json').exists())
        self.assertEqual([path.name for path in private.iterdir()], ['lock'])

    def test_stale_state_never_signals_the_recorded_foreign_pid(self):
        private = self.root / 'native-access-linux-wine'
        private.mkdir(mode=0o700)
        auth = private / ('xauthority-' + 'a' * 32)
        auth.write_bytes(_authority(9, b'a' * 16))
        auth.chmod(0o600)
        state = private / 'display.json'
        state.write_text(json.dumps({'pid': 99999, 'start': 'old', 'display': 9,
                                    'authority': auth.name, 'wayland': 'wayland-0'}))
        state.chmod(0o600)
        def identity(pid):
            if pid == 99999:
                return 'different', ['/usr/bin/foreign-server']
            return self.identity(pid)
        with patch('wine_display.shutil.which', return_value='/usr/bin/Xwayland'), \
             patch('wine_display._slot', return_value=10), \
             patch('wine_display.subprocess.Popen', side_effect=self.create_child), \
             patch('wine_display._identity', side_effect=identity), \
             patch('wine_display._authenticated', return_value=True), \
             patch('os.kill', side_effect=AssertionError('must never signal state PID')):
            result = ensure_display(self.environment)
        self.assertEqual(result['DISPLAY'], ':10')
        self.assertFalse(self.children[0].terminated)
        self.assertTrue(auth.exists())

    def test_runtime_symlink_and_insecure_permissions_are_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with patch('wine_display.shutil.which', return_value='/usr/bin/Xwayland'):
            with self.assertRaises(DisplayError):
                ensure_display({**self.environment, 'XDG_RUNTIME_DIR': str(alias)})
            self.root.chmod(0o755)
            with self.assertRaises(DisplayError):
                ensure_display(self.environment)

    def test_slot_selection_preserves_existing_x11_socket_and_lock(self):
        occupied = {'/tmp/.X11-unix/X9', '/tmp/.X10-lock'}
        with patch('wine_display.os.path.lexists', side_effect=lambda value: value in occupied):
            self.assertEqual(_slot(), 11)

    def test_missing_xwayland_has_actionable_prerequisite_and_never_spawns(self):
        with patch('wine_display.shutil.which', return_value=None), \
             patch('wine_display.subprocess.Popen', side_effect=AssertionError('must not spawn')):
            with self.assertRaisesRegex(DisplayError, 'xorg-xwayland'):
                ensure_display(self.environment)


if __name__ == '__main__':
    unittest.main()
