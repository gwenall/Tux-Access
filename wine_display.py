"""Private authenticated nested Xwayland for a Wayland-only Wine session."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import struct
import subprocess
import time
import uuid


class DisplayError(RuntimeError):
    pass


def _owned(path, kind, private=True):
    try:
        info = path.lstat()
    except OSError as exc:
        raise DisplayError('Wine display runtime path is unavailable: ' + path.name) from exc
    matches = stat.S_ISDIR(info.st_mode) if kind == 'directory' else stat.S_ISREG(info.st_mode)
    if not matches or info.st_uid != os.getuid() or (private and info.st_mode & 0o077):
        raise DisplayError('Wine display runtime path is not a private user-owned ' + kind)


def _identity(pid):
    """Kernel start time distinguishes PID reuse without signaling a process."""
    raw = Path(f'/proc/{pid}/stat').read_text()
    start = raw[raw.rfind(')') + 2:].split()[19]
    argv = Path(f'/proc/{pid}/cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    return start, [os.fsdecode(value) for value in argv]


def _authority(display, cookie):
    fields = [socket.gethostname().encode(), str(display).encode(), b'MIT-MAGIC-COOKIE-1', cookie]
    return struct.pack('>H', 256) + b''.join(struct.pack('>H', len(value)) + value for value in fields)


def _argv(binary, display, authority):
    # A minimal Wayland compositor need not provide an X11 window manager.
    # This tested rootful window supplies its own decorations and software path.
    return [binary, ':' + str(display), '-auth', str(authority), '-nolisten', 'tcp',
            '-geometry', '1280x800', '-decorate', '-shm', '-glamor', 'off']


def _cookie(authority):
    raw = authority.read_bytes()
    if len(raw) > 1024 or len(raw) < 2 or raw[:2] != struct.pack('>H', 256):
        raise DisplayError('Invalid private Wine display authority')
    offset, fields = 2, []
    for _ in range(4):
        if offset + 2 > len(raw):
            raise DisplayError('Invalid private Wine display authority')
        length = struct.unpack_from('>H', raw, offset)[0]
        offset += 2
        fields.append(raw[offset:offset + length])
        offset += length
    if offset != len(raw) or fields[2] != b'MIT-MAGIC-COOKIE-1' or len(fields[3]) != 16:
        raise DisplayError('Invalid private Wine display authority')
    return fields[3]


def _authenticated(display, cookie):
    """X11 setup handshake proves this socket accepts our private authority."""
    name = b'MIT-MAGIC-COOKIE-1'
    request = struct.pack('<BBHHHHH', ord('l'), 0, 11, 0, len(name), len(cookie), 0)
    request += name + b'\0' * ((-len(name)) % 4) + cookie + b'\0' * ((-len(cookie)) % 4)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            connection.connect(f'/tmp/.X11-unix/X{display}')
            connection.sendall(request)
            reply = b''
            while len(reply) < 8:
                chunk = connection.recv(8 - len(reply))
                if not chunk:
                    return False
                reply += chunk
            return reply[0] == 1 and struct.unpack_from('<H', reply, 2)[0] == 11
    except OSError:
        return False


def _runtime(environment):
    value = environment.get('XDG_RUNTIME_DIR')
    if not value or not Path(value).is_absolute():
        raise DisplayError('Wine needs a desktop runtime directory. Open Tuxaccess from your graphical session.')
    base = Path(value)
    _owned(base, 'directory')
    for parent in (base, *base.parents):
        if parent.is_symlink():
            raise DisplayError('Wine display runtime directory has symlink ancestry')
    wayland = environment.get('WAYLAND_DISPLAY')
    if not wayland:
        raise DisplayError('Wine needs a graphical Linux session. Open Tuxaccess from your desktop.')
    wayland_path = Path(wayland) if Path(wayland).is_absolute() else base / wayland
    try:
        info = wayland_path.lstat()
    except OSError as exc:
        raise DisplayError('The selected Wayland display socket is unavailable. Open the launcher from the desktop.') from exc
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise DisplayError('The selected Wayland display is not a user-owned socket')
    private = base / 'native-access-linux-wine'
    try:
        private.mkdir(mode=0o700)
    except FileExistsError:
        pass
    _owned(private, 'directory')
    return private


def _reuse(private, binary, wayland):
    state_path = private / 'display.json'
    if not state_path.exists() and not state_path.is_symlink():
        return None
    _owned(state_path, 'file')
    if state_path.stat().st_size > 4096:
        raise DisplayError('Invalid private Wine display state')
    try:
        state = json.loads(state_path.read_text())
        if not isinstance(state, dict) or type(state.get('pid')) is not int or type(state.get('display')) is not int:
            return None
        if state.get('wayland') != wayland:
            return None
        if not 9 <= state['display'] <= 63 or not re.fullmatch(r'xauthority-[0-9a-f]{32}', state.get('authority', '')):
            return None
        authority = private / state['authority']
        if not authority.exists() and not authority.is_symlink():
            return None
        _owned(authority, 'file')
        start, argv = _identity(state['pid'])
        expected = _argv(binary, state['display'], authority)
        if state.get('start') != start or argv != expected:
            return None
        if not _authenticated(state['display'], _cookie(authority)):
            return None
        return {**state, 'authority_path': str(authority)}
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None


def _slot():
    for display in range(9, 64):
        if not os.path.lexists(f'/tmp/.X11-unix/X{display}') and not os.path.lexists(f'/tmp/.X{display}-lock'):
            return display
    raise DisplayError('No free private Xwayland display slot is available')


def ensure_display(environment=None, cancelled=None, timeout=15):
    """Preserve X11 desktops; start/reuse only our authenticated nested server.

    Returns DISPLAY/XAUTHORITY overrides. No cookie is returned or logged.
    The server remains available for subsequent Wine windows and launcher runs.
    """
    environment = dict(os.environ if environment is None else environment)
    if environment.get('DISPLAY'):
        return {key: environment[key] for key in ('DISPLAY', 'XAUTHORITY') if key in environment}
    binary = shutil.which('Xwayland')
    if not binary:
        raise DisplayError('Wine needs Xwayland on this Wayland desktop. Install the Arch xorg-xwayland package and retry.')
    binary = str(Path(binary).absolute())
    private = _runtime(environment)
    import fcntl
    lock_path = private / 'lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        _owned(lock_path, 'file')
        deadline = time.monotonic() + timeout
        while True:
            if cancelled and cancelled():
                raise DisplayError('Wine display preparation cancelled')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DisplayError('Wine display preparation is busy. Retry after the current operation completes.')
                time.sleep(0.1)
        state = _reuse(private, binary, environment.get('WAYLAND_DISPLAY'))
        if state:
            return {'DISPLAY': ':' + str(state['display']), 'XAUTHORITY': state['authority_path']}
        display = _slot()
        authority = private / ('xauthority-' + uuid.uuid4().hex)
        cookie = os.urandom(16)
        with authority.open('xb') as output:
            output.write(_authority(display, cookie))
        authority.chmod(0o600)
        argv = _argv(binary, display, authority)
        process = None
        published = False
        try:
            try:
                process = subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True)
            except OSError as exc:
                raise DisplayError('Managed Xwayland could not start. Check the xorg-xwayland package and graphical session.') from exc
            while time.monotonic() < deadline:
                if cancelled and cancelled():
                    raise DisplayError('Wine display preparation cancelled')
                if process.poll() is not None:
                    raise DisplayError('Managed Xwayland could not start. Check the Wayland session and xorg-xwayland package.')
                if _authenticated(display, cookie):
                    try:
                        start, actual = _identity(process.pid)
                    except (OSError, IndexError) as exc:
                        raise DisplayError('Managed Xwayland ended during startup. Check the graphical session.') from exc
                    if actual != argv:
                        raise DisplayError('Managed Xwayland process identity changed during startup')
                    state = {'pid': process.pid, 'start': start, 'display': display,
                             'authority': authority.name, 'wayland': environment.get('WAYLAND_DISPLAY')}
                    temporary = private / ('state-' + uuid.uuid4().hex)
                    try:
                        with temporary.open('x', encoding='utf-8') as output:
                            json.dump(state, output)
                        temporary.chmod(0o600)
                        target = private / 'display.json'
                        if target.exists() or target.is_symlink():
                            _owned(target, 'file')
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    published = True
                    return {'DISPLAY': ':' + str(display), 'XAUTHORITY': str(authority)}
                time.sleep(0.1)
            raise DisplayError(f'Managed Xwayland did not become ready within {timeout:g} seconds. Check the graphical session and retry.')
        finally:
            if not published:
                # Only the Popen child from this call is signaled; no PID from state.
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                authority.unlink(missing_ok=True)
    finally:
        os.close(fd)
