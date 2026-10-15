"""System-browser NI authorization with a private native callback receiver."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import webbrowser

from tux_access.auth.oauth import APP_REDIRECT, BROWSER_REDIRECT, authorize_url, callback_code, new_verifier
from tux_access.auth.callback import CallbackReceiver, CallbackError
from tux_access import __file__ as package_file

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
               _desktop_quote(str(Path(package_file).with_name('__main__.py').resolve())) +
               ' --oauth-callback %u')
    text = ('[Desktop Entry]\nType=Application\nName=Tux Access\n'
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


def browser_login_banner(parent=None, *, opener=None, prepare_handler=None, runtime_dir=None, force_login=False):
    from PySide6 import QtCore, QtWidgets

    class Banner(QtWidgets.QFrame):
        finished = QtCore.Signal(int)

        def __init__(self):
            super().__init__(parent)
            self.setObjectName('signInBanner')
            self._result = 0
            self._finished = False
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
            buttons = QtWidgets.QHBoxLayout()
            self.retry_button = QtWidgets.QPushButton('Try again')
            self.retry_button.clicked.connect(self.retry)
            self.retry_button.hide()
            buttons.addWidget(self.retry_button)
            buttons.addStretch()
            self.cancel_button = QtWidgets.QPushButton('Cancel sign-in')
            self.cancel_button.clicked.connect(self.reject)
            buttons.addWidget(self.cancel_button)
            layout.addLayout(buttons)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.poll_callbacks)
            self.finished.connect(self.cleanup)

        def result(self):
            return self._result

        def accept(self):
            self._finish(1)

        def reject(self):
            self.code = self.verifier = None
            self._finish(0)

        def _finish(self, result):
            if self._finished:
                return
            self._finished = True
            self._result = result
            self.finished.emit(result)

        def retry(self):
            self.cleanup()
            self.verifier = new_verifier()
            self.state = secrets.token_urlsafe(32)
            self.code = None
            self.retry_button.hide()
            self.start()

        def start(self):
            try:
                (prepare_handler or register_browser_callback)()
                self.receiver.start()
                self.deadline = time.monotonic() + 7200
                self.timer.start(75)
                url = authorize_url(self.verifier, self.state, self.redirect_uri, force_login=force_login)
                if not (opener or webbrowser.open)(url):
                    raise RuntimeError('No browser opened.')
                self.notice.setText('Waiting for NI to return to Tux Access. Allow your browser to open this application when asked.')
            except (OSError, RuntimeError, webbrowser.Error):
                self.cleanup()
                self.notice.setText('Could not open browser sign-in. Check your default browser and try again.')
                self.retry_button.show()

        def poll_callbacks(self):
            if self.deadline is not None and time.monotonic() > self.deadline:
                self.cleanup()
                self.notice.setText('Sign-in expired. Cancel and start a new sign-in.')
                self.retry_button.show()
                return
            try:
                callbacks = self.receiver.poll()
            except CallbackError:
                self.cleanup()
                self.notice.setText('Could not receive the browser callback. Cancel and retry sign-in.')
                self.retry_button.show()
                return
            for uri in callbacks:
                try:
                    code = callback_code(uri, self.state, APP_REDIRECT)
                except ValueError:
                    self.notice.setText('NI returned an invalid or declined authorization. Cancel and retry sign-in.')
                    self.retry_button.show()
                    continue
                self.code = code
                self.accept()
                break

        def cleanup(self, *_):
            self.timer.stop()
            self.receiver.close()

        def closeEvent(self, event):
            self.reject()
            super().closeEvent(event)

    return Banner()


# Compatibility for callers of the former factory; it now returns an inline widget.
browser_login_dialog = browser_login_banner
