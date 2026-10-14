"""Private POSIX delivery of an OAuth callback to a waiting launcher.

``CallbackReceiver`` is a nonblocking Unix datagram receiver. Call ``start()``
or use it as a context manager, call ``poll()`` from the GUI timer, and always
``close()`` afterwards. ``forward_callback(uri)`` sends one callback; True means
the kernel accepted delivery, NOT that OAuth authorization succeeded.

Only the exact ``native-access://authorize`` target is accepted. The receiving
application must additionally validate OAuth state, PKCE, expiry and errors.
No callback is logged or stored on disk. Exact duplicate messages are discarded
for the receiver's entire lifetime. The bounded replay cache fails closed after
``max_callbacks`` distinct messages, so use a receiver per sign-in transaction.
An existing active receiver is never replaced. This module needs Python 3.10+
on POSIX and an owned, private XDG_RUNTIME_DIR (normally /run/user/<uid>).
"""
import errno
import hashlib
import os
from pathlib import Path
import re
import socket
import stat
from urllib.parse import urlsplit


MAX_URI_BYTES = 16384
_DIRECTORY = 'native-access-linux-oauth'
_SOCKET = 'callback.sock'
_MAX_POLL_MESSAGES = 32


class CallbackError(RuntimeError):
    """Generic delivery failure; messages never contain callback values."""


def _uri_bytes(uri):
    if (not isinstance(uri, str) or not uri or
            any(ord(character) <= 32 or ord(character) == 127 for character in uri) or
            re.search(r'%0[ad]', uri, re.IGNORECASE)):
        raise CallbackError('Invalid authorization callback.')
    try:
        payload = uri.encode('utf-8', errors='strict')
        parsed = urlsplit(uri)
    except (ValueError, UnicodeError):
        raise CallbackError('Invalid authorization callback.') from None
    if (len(payload) > MAX_URI_BYTES or parsed.scheme != 'native-access' or
            parsed.netloc != 'authorize' or parsed.path or parsed.fragment or
            not parsed.query):
        raise CallbackError('Invalid authorization callback.')
    return payload


def _private_directory(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
            stat.S_IMODE(info.st_mode) == 0o700)


def _runtime_path(runtime_dir):
    if os.name != 'posix' or not hasattr(socket, 'AF_UNIX'):
        raise CallbackError('Private callback delivery requires POSIX.')
    value = runtime_dir if runtime_dir is not None else os.environ.get('XDG_RUNTIME_DIR')
    if not isinstance(value, (str, os.PathLike)):
        raise CallbackError('A private runtime directory is required.')
    try:
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts:
            raise CallbackError('A private runtime directory is required.')
        # Reject symlink components before opening the runtime directory.
        for component in reversed((path,) + tuple(path.parents)):
            if not stat.S_ISDIR(os.lstat(component).st_mode):
                raise CallbackError('A private runtime directory is required.')
        if not _private_directory(os.lstat(path)):
            raise CallbackError('A private runtime directory is required.')
    except (OSError, ValueError):
        raise CallbackError('A private runtime directory is required.') from None
    return path


def _open_directory(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _open_project(runtime_dir, create):
    runtime_path = _runtime_path(runtime_dir)
    runtime_fd = project_fd = None
    try:
        runtime_fd = _open_directory(runtime_path)
        if not _private_directory(os.fstat(runtime_fd)):
            raise CallbackError('A private runtime directory is required.')
        if create:
            try:
                os.mkdir(_DIRECTORY, 0o700, dir_fd=runtime_fd)
            except FileExistsError:
                pass
        project_fd = os.open(_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY |
                             os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=runtime_fd)
        if not _private_directory(os.fstat(project_fd)):
            raise CallbackError('A private callback directory is required.')
        project_path = runtime_path / _DIRECTORY
        # Verify the pathname socket operations will use matches the opened fd.
        info = os.lstat(project_path)
        opened = os.fstat(project_fd)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise CallbackError('A private callback directory is required.')
        result = (project_path, project_fd)
        project_fd = None
        return result
    except CallbackError:
        raise
    except OSError:
        raise CallbackError('Private callback delivery is unavailable.') from None
    finally:
        if project_fd is not None:
            os.close(project_fd)
        if runtime_fd is not None:
            os.close(runtime_fd)


def _socket_info(directory_fd):
    try:
        info = os.stat(_SOCKET, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o600):
        raise CallbackError('The callback path is not private.')
    return info


def _same_file(first, second):
    return (first is not None and second is not None and
            (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino))


def _remove_owned_socket(directory_fd, expected):
    """Unlink only the same verified socket, using the owned directory fd."""
    try:
        current = os.stat(_SOCKET, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (stat.S_ISSOCK(current.st_mode) and current.st_uid == os.getuid() and
            _same_file(current, expected)):
        os.unlink(_SOCKET, dir_fd=directory_fd)


class CallbackReceiver:
    """Bounded, nonblocking callback delivery for one sign-in transaction."""

    def __init__(self, runtime_dir=None, max_callbacks=128):
        if (not isinstance(max_callbacks, int) or isinstance(max_callbacks, bool) or
                not 1 <= max_callbacks <= 1024):
            raise ValueError('Expected a callback limit between 1 and 1024.')
        self._runtime_dir = runtime_dir
        self._max_callbacks = max_callbacks
        self._socket = None
        self._directory_fd = None
        self._owned_info = None
        self._seen = set()

    def start(self):
        if self._socket is not None:
            return self
        project_path, directory_fd = _open_project(self._runtime_dir, create=True)
        channel = None
        owned_info = None
        try:
            channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            channel.setblocking(False)
            path = str(project_path / _SOCKET)
            existing = _socket_info(directory_fd)
            if existing is not None:
                # Connecting does not send a message. A live socket is preserved.
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                try:
                    probe.connect(path)
                except OSError as error:
                    if error.errno != errno.ECONNREFUSED:
                        raise CallbackError('Another callback receiver is present.') from None
                    _remove_owned_socket(directory_fd, existing)
                else:
                    raise CallbackError('Another callback receiver is present.')
                finally:
                    probe.close()
            channel.bind(path)
            owned_info = os.stat(_SOCKET, dir_fd=directory_fd, follow_symlinks=False)
            # The parent directory is private before the socket exists.
            os.chmod(_SOCKET, 0o600, dir_fd=directory_fd)
            checked = _socket_info(directory_fd)
            if not _same_file(owned_info, checked):
                raise CallbackError('Private callback delivery is unavailable.')
            self._socket = channel
            self._directory_fd = directory_fd
            self._owned_info = checked
            return self
        except (OSError, CallbackError):
            if channel is not None:
                channel.close()
            if owned_info is not None:
                try:
                    _remove_owned_socket(directory_fd, owned_info)
                except (OSError, CallbackError):
                    pass
            os.close(directory_fd)
            raise CallbackError('Unable to start a private callback receiver.') from None

    def poll(self, max_messages=8):
        """Drain at most max_messages datagrams without waiting; reject duplicates."""
        if (not isinstance(max_messages, int) or isinstance(max_messages, bool) or
                not 1 <= max_messages <= _MAX_POLL_MESSAGES):
            raise ValueError('Expected a poll limit between 1 and 32.')
        if self._socket is None:
            return []
        callbacks = []
        for _ in range(max_messages):
            try:
                payload = self._socket.recv(MAX_URI_BYTES + 1)
            except BlockingIOError:
                break
            except OSError:
                raise CallbackError('Private callback delivery failed.') from None
            try:
                uri = payload.decode('utf-8', errors='strict')
                validated = _uri_bytes(uri)
            except (UnicodeError, CallbackError):
                continue
            digest = hashlib.sha256(validated).digest()
            if digest in self._seen or len(self._seen) >= self._max_callbacks:
                continue
            self._seen.add(digest)
            callbacks.append(uri)
        return callbacks

    def close(self):
        channel, directory_fd, owned_info = self._socket, self._directory_fd, self._owned_info
        self._socket = self._directory_fd = self._owned_info = None
        if channel is not None:
            channel.close()
        if directory_fd is not None:
            try:
                _remove_owned_socket(directory_fd, owned_info)
            except (OSError, CallbackError):
                # Preserve any path that has been replaced or is no longer safe.
                pass
            finally:
                os.close(directory_fd)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exception):
        self.close()


def forward_callback(uri, runtime_dir=None, timeout=0.5):
    """Send one validated URI; False means no receiver or a full queue.

    Malformed callbacks, unsafe paths and other failures raise CallbackError.
    No OAuth acceptance is implied by a True result.
    """
    payload = _uri_bytes(uri)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 5:
        raise ValueError('Expected a delivery timeout between 0 and 5 seconds.')
    project_path, directory_fd = _open_project(runtime_dir, create=False)
    try:
        if _socket_info(directory_fd) is None:
            return False
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.settimeout(timeout)
            try:
                return channel.sendto(payload, str(project_path / _SOCKET)) == len(payload)
            except (TimeoutError, BlockingIOError, FileNotFoundError, ConnectionRefusedError):
                return False
            except OSError:
                raise CallbackError('Private callback delivery failed.') from None
    except OSError:
        raise CallbackError('Private callback delivery failed.') from None
    finally:
        os.close(directory_fd)
