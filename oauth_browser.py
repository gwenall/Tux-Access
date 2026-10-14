"""System-browser NI authorization with a private native callback receiver."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import webbrowser

from account_auth import APP_REDIRECT, BROWSER_REDIRECT, authorize_url, callback_code, new_verifier
from oauth_callback import CallbackReceiver, CallbackError

HANDLER_ID = 'native-access-linux-oauth.desktop'


def _desktop_quote(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise RuntimeError('Invalid browser callback launcher.')
    # Minimal desktops use xdg-open's simple Exec parser. Leave safe paths
    # unquoted so it can dispatch them; keep standard quoting for other paths.
    if value and re.fullmatch(r'[A-Za-z0-9_./:-]+', value):
        return value
    for old, new in [('\\', '\\\\\\\\'), ('"', '\\\\"'), ('`', '\\\\`'), ('$', '\\\\$')]:
        value = value.replace(old, new)
    return '"' + value.replace('%', '%%') + '"'


def register_browser_callback():
    """Register the user-local native-access URI handler for this interpreter.

    Callback URLs travel directly through argv into the private runtime socket;
    neither the desktop file nor any other file stores callback values.
    """
    if sys.platform != 'linux':
        raise RuntimeError('System-browser callback registration requires Linux.')
    base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    if not base.is_absolute():
        raise RuntimeError('A desktop data directory is required.')
    directory = base / 'applications'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / HANDLER_ID
    if destination.is_symlink():
        raise RuntimeError('The browser callback launcher is not a regular file.')
    command = (_desktop_quote(sys.executable) + ' ' +
               _desktop_quote(str(Path(__file__).with_name('launcher.py').resolve())) +
               ' --oauth-callback %u')
    text = ('[Desktop Entry]\nType=Application\nName=Native Access Linux\n'
            'NoDisplay=true\nTerminal=false\nExec=' + command + '\n'
            'MimeType=x-scheme-handler/native-access;\n')
    destination.write_text(text, encoding='utf-8')
    try:
        result = subprocess.run(['xdg-mime', 'default', HANDLER_ID,
                                 'x-scheme-handler/native-access'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=10, check=False)
        if result.returncode:
            raise RuntimeError('Could not register the browser callback launcher.')
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Could not register the browser callback launcher.') from None


def browser_login_dialog(parent=None, *, opener=None, prepare_handler=None, runtime_dir=None):
    from PySide6 import QtCore, QtWidgets

    class Dialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle('Sign in to Native Instruments')
            self.resize(600, 180)
            self.verifier = new_verifier()
            self.state = secrets.token_urlsafe(32)
            self.code = None
            # The original HTTPS OAuth redirect remains the token redemption
            # redirect even after NI relays its query to the native scheme.
            self.redirect_uri = BROWSER_REDIRECT
            self.receiver = CallbackReceiver(runtime_dir)
            self.deadline = None
            layout = QtWidgets.QVBoxLayout(self)
            heading = QtWidgets.QLabel('Continue signing in with Native Instruments in your browser.')
            heading.setWordWrap(True)
            layout.addWidget(heading)
            self.notice = QtWidgets.QLabel('Preparing browser sign-in…')
            self.notice.setWordWrap(True)
            layout.addWidget(self.notice)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.poll_callbacks)
            self.finished.connect(self.cleanup)

        def start(self):
            try:
                (prepare_handler or register_browser_callback)()
                self.receiver.start()
                self.deadline = time.monotonic() + 7200
                self.timer.start(75)
                url = authorize_url(self.verifier, self.state, self.redirect_uri)
                if not (opener or webbrowser.open)(url):
                    raise RuntimeError('No browser opened.')
                self.notice.setText('Waiting for NI to return to Native Access Linux. Allow your browser to open this application when asked.')
            except (OSError, RuntimeError, webbrowser.Error):
                self.cleanup()
                self.notice.setText('Could not open browser sign-in. Check your default browser and try again.')

        def poll_callbacks(self):
            if self.deadline is not None and time.monotonic() > self.deadline:
                self.cleanup()
                self.notice.setText('Sign-in expired. Cancel and start a new sign-in.')
                return
            try:
                callbacks = self.receiver.poll()
            except CallbackError:
                self.cleanup()
                self.notice.setText('Could not receive the browser callback. Cancel and retry sign-in.')
                return
            for uri in callbacks:
                try:
                    code = callback_code(uri, self.state, APP_REDIRECT)
                except ValueError:
                    self.notice.setText('NI returned an invalid or declined authorization. Cancel and retry sign-in.')
                    continue
                self.code = code
                self.accept()
                break

        def cleanup(self, *_):
            self.timer.stop()
            self.receiver.close()

        def closeEvent(self, event):
            self.cleanup()
            super().closeEvent(event)

    return Dialog()
