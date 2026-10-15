"""Linux/POSIX callback transport tests. No credentials or NI requests."""
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

from tux_access.auth.callback import CallbackError, CallbackReceiver, MAX_URI_BYTES, forward_callback


@unittest.skipUnless(os.name == 'posix' and hasattr(socket, 'AF_UNIX'), 'POSIX sockets required')
class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temporary.name) / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.uri = 'native-access://authorize?code=test-code&state=test-state'
        self.path = self.runtime / 'native-access-linux-oauth' / 'callback.sock'
        self.receivers = []

    def tearDown(self):
        for receiver in self.receivers:
            receiver.close()
        self.temporary.cleanup()

    def receiver(self, **options):
        instance = CallbackReceiver(self.runtime, **options)
        self.receivers.append(instance)
        return instance.start()

    def raw_send(self, payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.sendto(payload, str(self.path))

    def test_delivery_private_permissions_and_cleanup(self):
        with CallbackReceiver(self.runtime) as receiver:
            self.assertEqual(receiver.poll(), [])
            self.assertTrue(forward_callback(self.uri, self.runtime))
            self.assertEqual(receiver.poll(), [self.uri])
            self.assertEqual(receiver.poll(), [])
            self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertFalse(self.path.exists())

    def test_runtime_environment(self):
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.runtime)}):
            with CallbackReceiver() as receiver:
                self.assertTrue(forward_callback(self.uri))
                self.assertEqual(receiver.poll(), [self.uri])

    def test_malformed_and_oversize_messages_rejected_by_both_sides(self):
        receiver = self.receiver()
        invalid = ('https://authorize?code=x', 'native-access://authorize.evil?code=x',
                   'native-access://authorize/other?code=x', 'native-access://x@authorize?code=x',
                   'native-access://authorize:80?code=x', 'native-access://authorize?code=x#fragment',
                   'native-access://authorize?code=x\n', 'native-access://authorize?code=%0d',
                   ' native-access://authorize?code=x',
                   'native-access://authorize', 'native-access://authorize?code=' + 'x' * MAX_URI_BYTES)
        for uri in invalid:
            with self.subTest(uri=uri[:70]):
                with self.assertRaisesRegex(CallbackError, r'^Invalid authorization callback\.$'):
                    forward_callback(uri, self.runtime)
                self.raw_send(uri.encode())
                self.assertEqual(receiver.poll(), [])
        self.raw_send(b'\xff')
        self.assertEqual(receiver.poll(), [])
        self.assertTrue(forward_callback(self.uri, self.runtime))
        self.assertEqual(receiver.poll(), [self.uri])

    def test_replay_and_bounded_delivery(self):
        receiver = self.receiver(max_callbacks=2)
        for uri in (self.uri, self.uri, self.uri + '2'):
            self.assertTrue(forward_callback(uri, self.runtime))
        self.assertEqual(receiver.poll(max_messages=1), [self.uri])
        self.assertEqual(receiver.poll(max_messages=1), [])
        self.assertEqual(receiver.poll(max_messages=1), [self.uri + '2'])
        self.assertTrue(forward_callback(self.uri + '3', self.runtime))
        self.assertEqual(receiver.poll(), [])

    def test_existing_live_receiver_is_preserved(self):
        receiver = self.receiver()
        original = self.path.stat().st_ino
        with self.assertRaises(CallbackError):
            self.receiver()
        self.assertEqual(self.path.stat().st_ino, original)
        self.assertTrue(forward_callback(self.uri, self.runtime))
        self.assertEqual(receiver.poll(), [self.uri])

    def test_stale_private_socket_can_be_replaced(self):
        self.path.parent.mkdir(mode=0o700)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stale:
            stale.bind(str(self.path))
            self.path.chmod(0o600)
        receiver = self.receiver()
        self.assertTrue(forward_callback(self.uri, self.runtime))
        self.assertEqual(receiver.poll(), [self.uri])

    def test_nonprivate_and_symlinked_runtime_rejected(self):
        self.runtime.chmod(0o755)
        with self.assertRaises(CallbackError):
            self.receiver()
        self.runtime.chmod(0o700)
        alias = self.runtime.parent / 'alias'
        alias.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(CallbackError):
            CallbackReceiver(alias).start()
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': ''}):
            with self.assertRaises(CallbackError):
                CallbackReceiver().start()

    def test_runtime_owned_by_another_uid_is_rejected(self):
        # Simulate launching as another user against this actual directory.
        with patch('tux_access.auth.callback.os.getuid', return_value=self.runtime.stat().st_uid + 1):
            with self.assertRaises(CallbackError):
                self.receiver()
            with self.assertRaises(CallbackError):
                forward_callback(self.uri, self.runtime)
        self.assertFalse(self.path.parent.exists())

    def test_symlinked_project_directory_is_rejected(self):
        target = self.runtime / 'other'
        target.mkdir(mode=0o700)
        self.path.parent.symlink_to(target, target_is_directory=True)
        with self.assertRaises(CallbackError):
            self.receiver()
        self.assertTrue(self.path.parent.is_symlink())
        self.assertEqual(list(target.iterdir()), [])

    def test_unsafe_project_and_socket_are_preserved(self):
        self.path.parent.mkdir(mode=0o755)
        self.path.parent.chmod(0o755)
        with self.assertRaises(CallbackError):
            self.receiver()
        self.path.parent.chmod(0o700)
        target = self.runtime / 'keep.txt'
        target.write_text('keep')
        self.path.symlink_to(target)
        with self.assertRaises(CallbackError):
            self.receiver()
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), 'keep')

    def test_close_does_not_remove_replacement_file(self):
        receiver = self.receiver()
        self.path.unlink()
        self.path.write_text('keep')
        receiver.close()
        self.assertEqual(self.path.read_text(), 'keep')

    def test_closed_receiver_and_missing_socket(self):
        receiver = self.receiver()
        receiver.close()
        receiver.close()
        self.assertEqual(receiver.poll(), [])
        self.assertFalse(forward_callback(self.uri, self.runtime))


if __name__ == '__main__':
    unittest.main()
