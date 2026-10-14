"""Native embedded OAuth callback handling; account credentials stay with NI.

The registered native redirect is observed in the reference application.
Actual fresh NI authorization must still be corroborated with user interaction.
"""
import secrets
from urllib.parse import urlsplit
from account_auth import APP_REDIRECT, new_verifier, authorize_url, callback_code

def login_dialog(parent=None):
    from PySide6 import QtCore, QtWidgets, QtWebEngineCore, QtWebEngineWidgets

    class Page(QtWebEngineCore.QWebEnginePage):
        callback = QtCore.Signal(str)
        rejected = QtCore.Signal(str)

        def javaScriptConsoleMessage(self, *args):
            # Provider console output can contain transient account credentials.
            pass

        def acceptNavigationRequest(self, url, navigation_type, main_frame):
            text = url.toString()
            parsed = urlsplit(text)
            if parsed.scheme == 'native-access':
                if main_frame:
                    self.callback.emit(text)
                return False
            if parsed.scheme == 'about' and text == 'about:blank':
                return True
            # Navigation uses verified HTTPS; OS/file/custom handlers are excluded.
            if parsed.scheme != 'https' or parsed.username or parsed.password:
                self.rejected.emit('Authentication navigation was rejected.')
                return False
            return True

    class Dialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle('Sign in to Native Instruments')
            self.resize(720, 760)
            self.verifier = new_verifier()
            self.state = secrets.token_urlsafe(32)
            self.code = None
            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(QtWidgets.QLabel('Sign in directly with Native Instruments. This launcher does not read your password.'))
            self.notice = QtWidgets.QLabel('Waiting for authorization…')
            self.notice.setWordWrap(True)
            layout.addWidget(self.notice)
            # No storage name => off-the-record cookies/cache, no disk profile.
            self.view = QtWebEngineWidgets.QWebEngineView(self)
            self.profile = QtWebEngineCore.QWebEngineProfile(self)
            self.page = Page(self.profile, self.view)
            self.view.setPage(self.page)
            self.page.callback.connect(self.accept_callback)
            self.page.rejected.connect(self.notice.setText)
            self.page.certificateError.connect(lambda error: error.rejectCertificate())
            layout.addWidget(self.view, 1)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def start(self):
            self.view.setUrl(QtCore.QUrl(authorize_url(
                self.verifier, self.state, APP_REDIRECT, force_login=True)))

        def accept_callback(self, url):
            try:
                self.code = callback_code(url, self.state, APP_REDIRECT)
            except ValueError:
                self.notice.setText('Authorization callback was rejected. Please retry sign-in.')
                return
            self.view.stop()
            self.accept()

        def closeEvent(self, event):
            self.view.stop()
            super().closeEvent(event)

    return Dialog()
