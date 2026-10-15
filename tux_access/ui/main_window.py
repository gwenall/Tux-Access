"""Native Qt launcher with account downloads and verified Linux installation."""
import argparse
import json
import re
from pathlib import Path
import queue
import threading
from PySide6 import QtCore, QtGui, QtWidgets
from tux_access.catalog.products import catalog_rows, product_values


def daemon_snapshot(endpoint):
    from tux_access.protocol.ntk import NtkClient, PROTOCOL_VERSION
    from tux_access.protocol.codec import encode, decode
    client = NtkClient(endpoint=endpoint, timeout_ms=3000)
    try:
        client.ping()
        version = client.version()
        products = catalog_rows(client.known_products())
        # Existing owned session only, transient; never cache or display tokens.
        envelope = {'header': {'version': dict(zip(('major', 'minor', 'micro'), PROTOCOL_VERSION))},
                    'auth0_access_token_request': {}}
        try:
            reply = decode('NtkMessage', client._exchange(encode('NtkMessage', envelope)))
            token = reply.get('auth0_access_token_response', {}).get('access_token')
            if not isinstance(token, str) or not token:
                token = None
        except Exception:
            # Catalog remains usable when no account session is available.
            token = None
        return products, version, token
    finally:
        client.close()


class SidebarArtwork(QtWidgets.QLabel):
    """Use only the sidebar's spare stretch space; never impose image height."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from tux_access.ui.sidebar_art import startup_artwork
        self.source_path = startup_artwork()
        self._original = QtGui.QPixmap(str(self.source_path)) if self.source_path else QtGui.QPixmap()
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(0, 8, 0, 8)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Musical Tux artwork')
        self.setToolTip('User-supplied musical Tux artwork')

    def sizeHint(self):
        return QtCore.QSize(144, 144)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = min(self.contentsRect().width(), self.contentsRect().height(), 148)
        if self._original.isNull() or size < 72:
            self.clear()
            return
        ratio = self.devicePixelRatioF()
        scaled = self._original.scaled(QtCore.QSize(round(size * ratio), round(size * ratio)),
                                       QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                       QtCore.Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.setPixmap(scaled)


class Launcher(QtWidgets.QMainWindow):
    def __init__(self, endpoint='tcp://127.0.0.1:5146'):
        super().__init__()
        from tux_access.settings import load_settings, default_settings, SettingsError
        settings_warning = None
        try:
            self.settings = load_settings()
        except (SettingsError, OSError, ValueError) as error:
            self.settings = default_settings()
            settings_warning = 'Settings could not be loaded. Defaults are active: ' + str(error)
        self._settings_warning = settings_warning
        self.endpoint = endpoint if endpoint != 'tcp://127.0.0.1:5146' else self.settings.reference_endpoint
        self.products, self.artifacts = [], []
        self._account_records = None
        self._local_records = []
        self._pending_uninstall = None
        self._inventory_unknown = False
        self._token = None
        self._refresh_token = None
        self._profile = {}
        self._login_banner = None
        self._verified_files = {}
        self._verified_artifacts = {}
        self.product_actions = []
        self._events = queue.Queue()
        self._busy = False
        self._closing = False
        self._cancel = threading.Event()
        self._product_states = {}
        self._active_product = None
        self._retry = None
        self._view = 'all'
        self._selected_identity = None
        self._settings_page = None
        self._about_page = None
        self._bundle_page = None
        self._bundle_product = None
        self._bundle_rows = []
        self._bundle_actions = []
        self._settings_controls = []
        self._options_product = None
        self._inline_artifacts = []
        self.setWindowTitle('Tux Access')
        screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 900)
        self.resize(min(1180, available.width() - 48), min(780, available.height() - 64))
        self.setMinimumSize(760, 540)
        self.setStyleSheet('''
            QMainWindow, QDialog { background: #101419; color: #e9edf2; }
            QWidget { color: #e9edf2; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }
            QFrame#sidebar { background: #171d25; border-radius: 16px; }
            QFrame#signInBanner { background: #20332c; border: 1px solid #527753; border-radius: 10px; }
            QFrame#uninstallBanner { background: #302327; border: 1px solid #86565e; border-radius: 10px; }
            QPushButton#destructive { background: #914b55; color: #ffffff; border-color: #b57882; }
            QPushButton#destructive:hover { background: #a75a65; }
            QLabel#muted { color: #98a6b8; }
            QLabel#title { font-size: 29px; font-weight: 650; }
            QLabel#brand { font-size: 18px; font-weight: 650; }
            QPushButton { background: #252e3b; border: 1px solid #354153; border-radius: 8px; padding: 9px 16px; min-height: 18px; }
            QPushButton:hover { background: #334156; border-color: #6d88ab; }
            QPushButton:disabled { color: #8390a1; background: #1c2430; border-color: #293240; }
            QPushButton#primary { background: #b8edb3; color: #132413; border: none; font-weight: 650; }
            QPushButton#primary:hover { background: #d0f6cc; }
            QPushButton#primary:disabled { background: #2d4032; color: #94ab97; }
            QPushButton#account { background: #b8edb3; color: #132413; border: none; border-radius: 20px; padding: 0; font-size: 18px; font-weight: 650; }
            QPushButton#nav { text-align: left; padding: 12px; border: none; background: transparent; }
            QPushButton#nav:checked { background: #2a3849; color: #cdebc9; }
            QLineEdit, QComboBox { background: #1b232e; border: 1px solid #354153; border-radius: 8px; padding: 10px; }
            QTableWidget { background: #151b23; alternate-background-color: #19212b; border: 1px solid #293443; border-radius: 12px; gridline-color: #283240; selection-background-color: #2d4157; }
            QTableWidget::item { padding: 10px; border-bottom: 1px solid #252f3d; }
            QHeaderView::section { background: #1b2531; color: #a7b7c9; padding: 12px; border: none; }
            QPlainTextEdit { background: #151d27; color: #b6c5d7; border: 1px solid #2b3748; border-radius: 10px; padding: 10px; }
            QProgressBar { background: #1d2733; border: none; border-radius: 6px; text-align: center; min-height: 22px; }
            QProgressBar::chunk { background: #527753; border-radius: 6px; }
            QMenu { background: #202a37; border: 1px solid #3c4b60; padding: 6px; }
            QMenu::item { padding: 9px 24px; }
            QMenu::item:selected { background: #35475e; }
            QTabWidget::pane { background: #151d27; border: 1px solid #354153; border-radius: 8px; }
            QScrollArea#settingsScroll, QWidget#settingsViewport, QWidget#settingsContents,
            QScrollArea#aboutScroll, QWidget#aboutViewport, QWidget#aboutContents { background: #151d27; }
            QTabBar::tab { background: #1b2531; color: #9eb0c6; padding: 12px 20px; }
            QTabBar::tab:selected { background: #304157; color: #e9edf2; }
            QCheckBox { spacing: 10px; }
            QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #6b7a8f; border-radius: 4px; background: #1b2531; }
            QCheckBox::indicator:checked { background: #b8edb3; border-color: #b8edb3; }
            QSplitter::handle { background: #25303e; }
            QScrollBar:vertical { background: #17202b; width: 12px; }
            QScrollBar::handle:vertical { background: #405168; min-height: 30px; border-radius: 5px; }
        ''')
        panel = QtWidgets.QWidget()
        self.setCentralWidget(panel)
        outer = QtWidgets.QHBoxLayout(panel)
        outer.setContentsMargins(18, 18, 24, 18)
        outer.setSpacing(24)
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(190)
        outer.addWidget(sidebar)
        navigation = QtWidgets.QVBoxLayout(sidebar)
        navigation.setContentsMargins(18, 24, 18, 20)
        brand = QtWidgets.QLabel('Tux Access')
        brand.setObjectName('brand')
        navigation.addWidget(brand)
        subtitle = QtWidgets.QLabel('Independent launcher')
        subtitle.setObjectName('muted')
        navigation.addWidget(subtitle)
        navigation.addSpacing(30)
        self.nav_buttons = []
        for text, view in [('All products', 'all'), ('Applications', 'applications'), ('Ready to install', 'supported'), ('Installed', 'installed')]:
            button = QtWidgets.QPushButton(text)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.setChecked(view == 'all')
            button.clicked.connect(lambda checked=False, value=view: self.set_view(value))
            navigation.addWidget(button)
            self.nav_buttons.append((button, view))
        self.sidebar_art = SidebarArtwork(sidebar)
        navigation.addWidget(self.sidebar_art, 1)
        self.settings_button = QtWidgets.QPushButton('Settings')
        self.settings_button.setObjectName('nav')
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(self.show_settings)
        navigation.addWidget(self.settings_button)
        self.about_button = QtWidgets.QPushButton('About')
        self.about_button.setObjectName('nav')
        self.about_button.setCheckable(True)
        self.about_button.clicked.connect(self.show_about)
        navigation.addWidget(self.about_button)
        self.account_status = QtWidgets.QLabel('Account not connected')
        self.account_status.setWordWrap(True)
        self.account_status.setObjectName('muted')
        navigation.addWidget(self.account_status)
        version = QtWidgets.QLabel('Python desktop · 0.9.2')
        version.setObjectName('muted')
        navigation.addWidget(version)
        content = QtWidgets.QWidget()
        outer.addWidget(content, 1)
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        self.sign_in_area = QtWidgets.QWidget()
        self.sign_in_layout = QtWidgets.QVBoxLayout(self.sign_in_area)
        self.sign_in_layout.setContentsMargins(0, 0, 0, 0)
        self.sign_in_area.hide()
        content_layout.addWidget(self.sign_in_area)
        self.uninstall_panel = QtWidgets.QFrame()
        self.uninstall_panel.setObjectName('uninstallBanner')
        confirm_layout = QtWidgets.QVBoxLayout(self.uninstall_panel)
        confirm_layout.setContentsMargins(14, 12, 14, 12)
        self.uninstall_notice = QtWidgets.QLabel()
        self.uninstall_notice.setWordWrap(True)
        confirm_layout.addWidget(self.uninstall_notice)
        confirm_actions = QtWidgets.QHBoxLayout()
        confirm_actions.addStretch()
        self.uninstall_cancel_button = QtWidgets.QPushButton('Cancel')
        self.uninstall_cancel_button.clicked.connect(self.cancel_uninstall_confirmation)
        confirm_actions.addWidget(self.uninstall_cancel_button)
        self.uninstall_confirm_button = QtWidgets.QPushButton('Uninstall')
        self.uninstall_confirm_button.setObjectName('destructive')
        self.uninstall_confirm_button.clicked.connect(self.confirm_uninstall)
        confirm_actions.addWidget(self.uninstall_confirm_button)
        confirm_layout.addLayout(confirm_actions)
        self.uninstall_panel.hide()
        content_layout.addWidget(self.uninstall_panel)
        self.pages = QtWidgets.QStackedWidget()
        content_layout.addWidget(self.pages, 1)
        self.library_page = QtWidgets.QWidget()
        self.pages.addWidget(self.library_page)
        layout = QtWidgets.QVBoxLayout(self.library_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = QtWidgets.QHBoxLayout()
        heading = QtWidgets.QLabel('Your library')
        heading.setObjectName('title')
        header.addWidget(heading)
        header.addStretch()
        self.actions = []
        self.account_menu = QtWidgets.QMenu(self)
        self.switch_account_action = self.account_menu.addAction('Switch account', self.sign_in)
        self.sign_out_action = self.account_menu.addAction('Sign out', self.sign_out)
        for text, method in [('Refresh', self.account_catalog), ('Sign in', self.account_clicked)]:
            button = QtWidgets.QPushButton(text)
            if text == 'Refresh':
                self.refresh_button = button
                button.setText('')
                button.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
                button.setIconSize(QtCore.QSize(20, 20))
                button.setFixedSize(40, 40)
                button.setToolTip('Refresh library')
                button.setAccessibleName('Refresh library')
                button.setStyleSheet('padding: 0;')
            if text == 'Sign in':
                button.setObjectName('primary')
                self.sign_in_button = button
            button.clicked.connect(method)
            header.addWidget(button)
            self.actions.append(button)
        layout.addLayout(header)
        self.library_summary = QtWidgets.QLabel('Sign in to see your products and available installers.')
        self.library_summary.setObjectName('muted')
        self.library_summary.setWordWrap(True)
        layout.addWidget(self.library_summary)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search your library…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render)
        layout.addWidget(self.search)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Product', 'Version', 'Type', 'State', 'Actions'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        # ResizeToContents sizes from header items and can ignore cell widgets.
        # Keep the action column wide enough for a styled "Installed" button.
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 132)
        self.table.setColumnWidth(1, 78)
        self.table.setColumnWidth(2, 100)
        self.table.itemSelectionChanged.connect(self.details)
        split.addWidget(self.table)
        detail_panel = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QtWidgets.QPlainTextEdit()
        self.detail.setReadOnly(True)
        detail_layout.addWidget(self.detail, 1)
        self.product_options_button = QtWidgets.QPushButton('Installation options')
        self.product_options_button.clicked.connect(self.open_selected_options)
        self.product_options_button.setEnabled(False)
        detail_actions = QtWidgets.QHBoxLayout()
        detail_actions.addWidget(self.product_options_button, 1)
        self.uninstall_button = QtWidgets.QPushButton('Uninstall')
        self.uninstall_button.setEnabled(False)
        self.uninstall_button.clicked.connect(self.request_selected_uninstall)
        self.uninstall_button.setToolTip('Select a qualified local installation to uninstall.')
        detail_actions.addWidget(self.uninstall_button)
        detail_layout.addLayout(detail_actions)
        split.addWidget(detail_panel)
        detail_panel.setMaximumHeight(180)
        self.detail.setMaximumHeight(130)
        self.detail.setPlaceholderText('Select a product to see installation support and details.')
        split.setSizes([470, 105])
        footer = QtWidgets.QWidget()
        content_layout.addWidget(footer)
        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)
        progress_row = QtWidgets.QHBoxLayout()
        footer_layout.addLayout(progress_row)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat('Idle')
        progress_row.addWidget(self.progress, 1)
        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.setMinimumHeight(38)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.cancel_button)
        self.retry_button = QtWidgets.QPushButton('Retry')
        self.retry_button.setMinimumHeight(38)
        self.retry_button.clicked.connect(self.retry_operation)
        self.retry_button.hide()
        progress_row.addWidget(self.retry_button)
        self.status = QtWidgets.QLabel('Sign in to load your library. Your password stays with Native Instruments.')
        self.status.setWordWrap(True)
        footer_layout.addWidget(self.status)
        limitation = QtWidgets.QLabel('File installation and NI license activation are separate. Activation is unverified.')
        limitation.setObjectName('muted')
        limitation.setWordWrap(True)
        footer_layout.addWidget(limitation)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(75)
        self.render()
        self.refresh_local_installations()
        if settings_warning:
            self.status.setText(self._safe_message(settings_warning))

    def set_view(self, view):
        self.cancel_uninstall_confirmation(announce=False)
        self._view = view
        self.pages.setCurrentWidget(self.library_page)
        self.settings_button.setChecked(False)
        self.about_button.setChecked(False)
        for button, value in self.nav_buttons:
            button.setChecked(value == view)
        self.render()

    def retry_operation(self):
        if not self._busy and self._retry:
            self._retry()

    def show_bundle(self, product):
        """Inspect confirmed collection membership without installing a bundle."""
        self.cancel_uninstall_confirmation(announce=False)
        self._bundle_product = product
        if self._bundle_page is None:
            page = QtWidgets.QWidget()
            page.setObjectName('bundlePage')
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            header = QtWidgets.QHBoxLayout()
            self.bundle_heading = QtWidgets.QLabel()
            self.bundle_heading.setObjectName('title')
            self.bundle_heading.setWordWrap(True)
            header.addWidget(self.bundle_heading, 1)
            back = QtWidgets.QPushButton('Back to library')
            back.clicked.connect(lambda: self.set_view(self._view))
            header.addWidget(back)
            self.bundle_refresh_button = QtWidgets.QPushButton()
            self.bundle_refresh_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
            self.bundle_refresh_button.setIconSize(QtCore.QSize(20, 20))
            self.bundle_refresh_button.setFixedSize(40, 40)
            self.bundle_refresh_button.setToolTip('Refresh collection')
            self.bundle_refresh_button.setAccessibleName('Refresh collection')
            self.bundle_refresh_button.setStyleSheet('padding: 0;')
            self.bundle_refresh_button.clicked.connect(self.account_catalog)
            header.addWidget(self.bundle_refresh_button)
            layout.addLayout(header)
            self.bundle_explanation = QtWidgets.QLabel()
            self.bundle_explanation.setWordWrap(True)
            self.bundle_explanation.setObjectName('muted')
            layout.addWidget(self.bundle_explanation)
            self.bundle_notice = QtWidgets.QLabel()
            self.bundle_notice.setWordWrap(True)
            layout.addWidget(self.bundle_notice)
            self.bundle_table = QtWidgets.QTableWidget(0, 5)
            self.bundle_table.setHorizontalHeaderLabels(['Product', 'Version', 'Type', 'State', 'Actions'])
            self.bundle_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.bundle_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.bundle_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.bundle_table.setAlternatingRowColors(True)
            self.bundle_table.setShowGrid(False)
            self.bundle_table.verticalHeader().hide()
            self.bundle_table.verticalHeader().setDefaultSectionSize(64)
            self.bundle_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            self.bundle_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            self.bundle_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.bundle_table.setColumnWidth(1, 78)
            self.bundle_table.setColumnWidth(2, 100)
            self.bundle_table.itemSelectionChanged.connect(self.bundle_details)
            layout.addWidget(self.bundle_table, 1)
            self.bundle_detail = QtWidgets.QPlainTextEdit()
            self.bundle_detail.setReadOnly(True)
            self.bundle_detail.setMaximumHeight(130)
            layout.addWidget(self.bundle_detail)
            self.pages.addWidget(page)
            self._bundle_page = page
        self._render_bundle()
        for button, _ in self.nav_buttons:
            button.setChecked(False)
        self.settings_button.setChecked(False)
        self.about_button.setChecked(False)
        self.pages.setCurrentWidget(self._bundle_page)

    def _bundle_reason(self, product):
        from tux_access.catalog.bundles import is_bundle
        if is_bundle(product):
            return self._unsupported_reason(product)
        if self._installed_locally(product):
            return 'A local installation is present. Launch is offered only when a qualified application profile can validate it.'
        if not product.get('bundleInstallerAvailable'):
            return 'Collection membership is confirmed, but no authorized installer is available in this account’s current metadata. Refresh can check again. Manual options do not grant download access.'
        if not self._supported(product):
            return self._unsupported_reason(product)
        return 'An authorized installer and supported backend are available. Install downloads, verifies and installs this individual product.'

    def _render_bundle(self):
        if self._bundle_page is None:
            return
        from tux_access.catalog.bundles import bundle_members
        from tux_access.catalog.bundles import is_bundle
        from tux_access.installation.backends import wine_spec
        selected = self.bundle_table.item(self.bundle_table.currentRow(), 0)
        selected_key = selected.data(QtCore.Qt.ItemDataRole.UserRole) if selected else None
        self._bundle_actions = []
        self._bundle_rows = bundle_members(self._bundle_product, self.products, self.artifacts) if self._bundle_product else []
        self.bundle_heading.setText(product_values(self._bundle_product)[0] if self._bundle_product else 'Collection')
        explicit = self._bundle_product is not None and any(key in self._bundle_product for key in ('bundleMembers', 'bundle_members'))
        source = ('Membership uses explicit bundle metadata supplied with this catalog record' if explicit else
                  'Membership comes from the NI public catalog snapshot dated 14 October 2026')
        self.bundle_explanation.setText('This collection has no single application installer. Choose an individual product below. ' +
                                        source + '; it does not establish download authorization or installation support.')
        self.bundle_notice.setText(f'{len(self._bundle_rows)} confirmed member products. Install and Launch act on one selected product at a time.' if self._bundle_rows else
                                   'Confirmed membership is not available in this collection’s current metadata. Refresh may update account installers; unrelated owned products are not substituted.')
        self.bundle_refresh_button.setEnabled(not self._busy and self._login_banner is None)
        self.bundle_table.blockSignals(True)
        self.bundle_table.clearSelection()
        self.bundle_table.setCurrentCell(-1, -1)
        self.bundle_table.setRowCount(0)
        self.bundle_table.setRowCount(len(self._bundle_rows))
        restored = None
        for row, member in enumerate(self._bundle_rows):
            nested_bundle = is_bundle(member)
            values = list(product_values(member))
            values[3] = self._product_states.get(self._product_key(member), values[3])
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, self._product_key(member))
                self.bundle_table.setItem(row, column, item)
            installed = self._installed_locally(member)
            launchable = installed and member.get('backend') == 'wine' and wine_spec(self._canonical_local_record(member)) is not None
            installable = not installed and self._supported(member) and member.get('bundleInstallerAvailable') is True
            uncertain = values[3] == 'Installation state needs refresh'
            button = QtWidgets.QPushButton('View products' if nested_bundle else 'Launch' if launchable else 'Install' if installable and not uncertain else 'Show options')
            button.setObjectName('primary' if launchable or installable else '')
            button.setEnabled(not self._busy and self._login_banner is None)
            action = self.show_bundle if nested_bundle else self.launch_wine_product if launchable else self.install_product if installable and not uncertain else self.open_install_options
            button.clicked.connect(lambda checked=False, p=member, handler=action: handler(p))
            button.setToolTip(self._bundle_reason(member))
            container = QtWidgets.QWidget()
            buttons = QtWidgets.QHBoxLayout(container)
            buttons.setContentsMargins(8, 4, 8, 4)
            buttons.addWidget(button)
            self.bundle_table.setCellWidget(row, 4, container)
            button.ensurePolished()
            button.setMinimumWidth(max(108, button.sizeHint().width(), button.fontMetrics().horizontalAdvance(button.text()) + 38))
            container.setMinimumWidth(button.minimumWidth() + 20)
            self._bundle_actions.append(button)
            if self._product_key(member) == selected_key:
                restored = row
        self._size_bundle_action_column()
        self.bundle_table.setColumnHidden(2, self.width() < 1000)
        self.bundle_table.doItemsLayout()
        if restored is not None:
            self.bundle_table.setCurrentCell(restored, 0)
            self.bundle_table.selectRow(restored)
        self.bundle_table.blockSignals(False)
        self.bundle_details()
        QtCore.QTimer.singleShot(0, self._size_bundle_action_column)

    def _size_bundle_action_column(self):
        self.bundle_table.setColumnWidth(4, max([148] + [button.minimumWidth() + 24 for button in self._bundle_actions]))
        self.bundle_table.doItemsLayout()

    def bundle_details(self):
        row = self.bundle_table.currentRow()
        if 0 <= row < len(self._bundle_rows):
            member = self._bundle_rows[row]
            self.bundle_detail.setPlainText(product_values(member)[0] + '\n' + self._bundle_reason(member))
        else:
            self.bundle_detail.setPlainText('Select a member to see its authorization and installation options.')

    def show_about(self):
        """Project context inside the main window, without affecting a job."""
        self.cancel_uninstall_confirmation(announce=False)
        if self._about_page is None:
            page = QtWidgets.QWidget()
            page.setObjectName('aboutPage')
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            heading = QtWidgets.QLabel('About Tux Access')
            heading.setObjectName('title')
            heading.setWordWrap(True)
            layout.addWidget(heading)
            version = QtWidgets.QLabel('Version 0.9.2 · Independent community prototype')
            version.setObjectName('muted')
            layout.addWidget(version)
            contents = QtWidgets.QWidget()
            contents.setObjectName('aboutContents')
            paragraphs = QtWidgets.QVBoxLayout(contents)
            paragraphs.setContentsMargins(22, 22, 22, 22)
            paragraphs.setSpacing(20)
            for text in (
                'Tux Access is an independent, unofficial Linux launcher and product manager for Native Instruments software. It provides an alternative workflow where Native Access 2 is unavailable or does not work on Linux. Linux support has been a recurring request in the NI community for years.',
                'Not affiliated with, endorsed by, or supported by Native Instruments.',
                'The launcher is released under the MIT license. Native Instruments software remains subject to its own licenses and account requirements.',
                'Native Instruments, Native Access and product names belong to their respective owners and are used to identify the software this project works with. Tux Access does not grant product licenses or bypass activation.',
                'This is a prototype. Native Arch and managed Wine workflows cover only qualified products, exact versions and supported configurations. File installation does not establish successful application startup or NI activation. Audio, plug-in and hardware/controller compatibility require separate validation.',
            ):
                label = QtWidgets.QLabel(text)
                label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
                paragraphs.addWidget(label)
            sources = QtWidgets.QLabel(
                'NI community discussions:<br>'
                '<a href="https://community.native-instruments.com/discussion/355/petition-for-linux/p2" style="color:#b8edb3">Petition for Linux</a><br>'
                '<a href="https://community.native-instruments.com/discussion/5666/native-instruments-products-natively-on-linux/p2" style="color:#b8edb3">Native Instruments products natively on Linux</a>')
            sources.setWordWrap(True)
            sources.setTextFormat(QtCore.Qt.TextFormat.RichText)
            sources.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.LinksAccessibleByMouse |
                                           QtCore.Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
            sources.setOpenExternalLinks(True)
            paragraphs.addWidget(sources)
            paragraphs.addStretch()
            scroll = QtWidgets.QScrollArea()
            scroll.setObjectName('aboutScroll')
            scroll.viewport().setObjectName('aboutViewport')
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            scroll.setWidget(contents)
            layout.addWidget(scroll, 1)
            self.pages.addWidget(page)
            self._about_page = page
        for button, _ in self.nav_buttons:
            button.setChecked(False)
        self.settings_button.setChecked(False)
        self.about_button.setChecked(True)
        self.pages.setCurrentWidget(self._about_page)

    def cancel_operation(self):
        if self._busy:
            self._cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText('Cancellation requested. Waiting for the current step to finish and clean up…')

    @classmethod
    def _product_key(cls, product):
        if product.get('upid'):
            return 'upid:' + str(product['upid'])
        return 'local:' + cls._title_key(product_values(product)[0])

    @classmethod
    def _installation_key(cls, product):
        from tux_access.catalog.applications import APPLICATIONS
        identity = APPLICATIONS.get(product.get('upid'))
        key = cls._title_key(identity[0] if identity else product_values(product)[0])
        return {'kontakt8player': 'kontakt8', 'reaktor6fx': 'reaktor6'}.get(key, key)

    def _application(self, product):
        from tux_access.catalog.applications import is_application
        return is_application(product) or (product.get('backend') == 'wine' and self._installed_locally(product))

    def _canonical_local_record(self, product):
        if isinstance(product.get('_local_installation'), dict):
            return product['_local_installation']
        return next((record for record in self._local_records
                     if self._installation_key(record) == self._installation_key(product)), product)

    def _removal_available(self, product):
        if product is None or not self._installed_locally(product):
            return False
        from tux_access.installation.remove import can_uninstall
        record = self._canonical_local_record(product)
        known = any(self._installation_key(local) == self._installation_key(product)
                    and local.get('prefix') == record.get('prefix')
                    and local.get('nativePackage') == record.get('nativePackage') for local in self._local_records)
        return known and can_uninstall(record, self.settings)

    def _load_account_rows(self, payload):
        self._inventory_unknown = False
        self._account_records = [dict(product) for product in catalog_rows(payload)]
        self.products = [dict(product) for product in self._account_records]

    def _rebuild_after_removal(self, records, target):
        unknown = records is None
        if self._account_records is None:
            # Offline fixtures/imports may predate an account snapshot. Preserve
            # account IDs; purely local records have no account identity.
            account = [dict(product) for product in self.products if product.get('upid') or
                       not any(self._installation_key(product) == self._installation_key(local)
                               for local in self._local_records)]
        else:
            account = [dict(product) for product in self._account_records]
        for product in account:
            if self._installation_key(product) != self._installation_key(target):
                continue
            for key in ('installedVersion', 'installationState', 'installationStatus', 'source', 'backend',
                        'nativePackage', 'prefix', 'executable', 'receipt', 'managed', 'binaryPath', '_local_installation'):
                product.pop(key, None)
            product.update(installed=False, status='Not installed')
        self._account_records = [dict(product) for product in account]
        self.products = account
        self._product_states.clear()
        if unknown:
            records = [record for record in self._local_records if
                       not (record.get('prefix') == target.get('prefix') if target.get('prefix') else
                            record.get('nativePackage') == target.get('nativePackage'))]
        self._merge_installed(records)
        self._inventory_unknown = unknown
        if unknown:
            for product in self.products:
                if self._installation_key(product) == self._installation_key(target):
                    self._product_states[self._product_key(product)] = 'Installation state needs refresh'

    def request_selected_uninstall(self):
        product = self._selected_product()
        if product is not None:
            self.request_uninstall(product)

    def request_uninstall(self, product):
        if self._busy or self._login_banner is not None:
            return
        if not self._removal_available(product):
            self.status.setText('Uninstall is available only for qualified launcher-owned packages and managed Wine installations. Verified legacy experiments are retained.')
            return
        self._pending_uninstall = {'product': product, 'record': dict(self._canonical_local_record(product))}
        self.uninstall_notice.setText('Uninstall ' + product_values(product)[0] + '? App files will be removed. Saved projects, content and settings will be retained.')
        self.uninstall_panel.show()
        self.uninstall_confirm_button.setFocus()

    def cancel_uninstall_confirmation(self, checked=False, *, announce=True):
        pending = self._pending_uninstall is not None
        self._pending_uninstall = None
        self.uninstall_panel.hide()
        if pending and announce:
            self.status.setText('Uninstall canceled. No files were removed.')

    def confirm_uninstall(self):
        if self._busy or self._login_banner is not None or self._pending_uninstall is None:
            return
        target = self._pending_uninstall
        self._pending_uninstall = None
        self.uninstall_panel.hide()
        from tux_access.installation.remove import can_uninstall, uninstall_product
        record, settings = target['record'], self.settings
        if not can_uninstall(record, settings):
            self.status.setText('This installation no longer qualifies for safe removal. Refresh the library before trying again.')
            return
        self._active_product = target['product']
        self._run('Verifying the selected installation before removal…',
                  lambda: uninstall_product(record, settings,
                                            progress=lambda event: self._installation_progress(event['stage'], event.get('current', 0),
                                                                                              event.get('total', 0), event.get('message', '')),
                                            cancelled=self._cancel.is_set),
                  'uninstall', download=True)

    def _selected_product(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item is None:
            return None
        key = item.data(int(QtCore.Qt.ItemDataRole.UserRole) + 1)
        return next((product for product in self.products if self._product_key(product) == key), None)

    def _supported(self, product):
        from tux_access.catalog.bundles import is_bundle
        if is_bundle(product):
            return False
        from tux_access.installation.install import can_install
        return can_install(product, self.settings)

    def refresh_local_installations(self):
        from tux_access.installation.install import installed_catalog
        settings = self.settings
        self._run('Checking local installation files…', lambda: installed_catalog(settings), 'local_catalog')

    def _installed_locally(self, product):
        state = self._product_states.get(self._product_key(product), product_values(product)[3]).casefold()
        if self._busy and state in ('verifying removal', 'removing', 'complete'):
            state = product_values(product)[3].casefold()
        local = product.get('source') in ('native-install', 'wine-install') or product.get('backend') in ('native', 'wine') or product.get('nativePackage')
        return 'installed' in state and 'not installed' not in state and (bool(local) or 'activation unverified' in state)

    def render(self, *_):
        from tux_access.installation.backends import wine_spec
        from tux_access.catalog.bundles import is_bundle
        self.product_actions = []
        query = self.search.text().casefold()
        selected = self.table.item(self.table.currentRow(), 0)
        if selected:
            self._selected_identity = selected.data(int(QtCore.Qt.ItemDataRole.UserRole) + 1)
        selected_identity = self._selected_identity
        rows = [(i, p) for i, p in enumerate(self.products) if query in product_values(p)[0].casefold()
                and (self._view != 'supported' or self._supported(p) and not self._installed_locally(p)
                     and self._product_states.get(self._product_key(p)) != 'Installation state needs refresh')
                and (self._view != 'installed' or self._installed_locally(p))
                and (self._view != 'applications' or self._application(p))]
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        restored_row = None
        for row, (index, product) in enumerate(rows):
            bundle = is_bundle(product)
            values = list(product_values(product))
            values[3] = self._product_states.get(self._product_key(product), values[3] or
                                               ('Ready to install' if self._supported(product) else 'Manual workflow'))
            if bundle:
                values[3] = 'Collection · choose products'
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, index)
                item.setData(int(QtCore.Qt.ItemDataRole.UserRole) + 1, self._product_key(product))
                self.table.setItem(row, column, item)
            actions = QtWidgets.QWidget()
            buttons = QtWidgets.QHBoxLayout(actions)
            buttons.setContentsMargins(8, 4, 8, 4)
            supported = self._supported(product)
            installed = self._installed_locally(product)
            uncertain = values[3] == 'Installation state needs refresh'
            launchable = installed and product.get('backend') == 'wine' and wine_spec(self._canonical_local_record(product)) is not None
            button = QtWidgets.QPushButton('View products' if bundle else 'Check state' if uncertain else 'Launch' if launchable else 'Installed' if installed else 'Retry' if values[3] in ('Failed', 'Cancelled') else 'Install')
            button.setObjectName('primary')
            button.setEnabled(not self._busy and self._login_banner is None and not uncertain and (bundle or launchable or not installed))
            callback = self.show_bundle if bundle else self.launch_wine_product if launchable else self.install_product
            button.clicked.connect(lambda checked=False, p=product, action=callback: action(p))
            button.setToolTip('View the confirmed products in this collection and choose an individual action.' if bundle else 'Start the verified local application.' if launchable else
                              'Download, verify and install this product automatically.' if supported else self._unsupported_reason(product))
            buttons.addWidget(button)
            # Attach before polishing: the inherited main-window font, weight
            # and padding determine the actual painted button size.
            self.table.setCellWidget(row, 4, actions)
            button.ensurePolished()
            button.setMinimumWidth(max(108, button.fontMetrics().horizontalAdvance(button.text()) + 38,
                                       button.sizeHint().width()))
            actions.setMinimumWidth(button.minimumWidth() + 20)
            self.product_actions.append(button)
            if self._product_key(product) == selected_identity:
                restored_row = row
        if restored_row is not None:
            self.table.setCurrentCell(restored_row, 0)
            self.table.selectRow(restored_row)
        else:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        self._size_action_column()
        ready_count = sum(self._supported(p) and not self._installed_locally(p) and
                          self._product_states.get(self._product_key(p)) != 'Installation state needs refresh' for p in self.products)
        self.library_summary.setText(f'{len(self.products)} products · {ready_count} ready to install · {len(rows)} shown' if self.products else
                                     'Sign in to see your products and available installers.')
        if not rows:
            self.detail.setPlainText('Local installation state needs refresh; other installed copies could not be checked.' if self._inventory_unknown else 'No products match this view.' if self.products else
                                     'Your library will appear here after sign-in.\nYou can also connect an existing session in Settings.')
        elif restored_row is None:
            self.detail.setPlainText('Select a product to see its installation support and locations.')
        self.product_options_button.setEnabled(restored_row is not None and not self._busy and self._login_banner is None)
        self.uninstall_button.setEnabled(not self._busy and self._login_banner is None and self._removal_available(self._selected_product()))
        self.table.blockSignals(False)
        if restored_row is not None:
            self.details()
        if self.pages.currentWidget() == self._bundle_page:
            self._render_bundle()
        QtCore.QTimer.singleShot(0, self._size_action_column)

    def _size_action_column(self):
        width = max([148] + [button.minimumWidth() + 24 for button in self.product_actions])
        self.table.setColumnWidth(4, width)
        # Reflow after scrollbar visibility and header section sizes settle.
        # This prevents index widgets from retaining the previous narrower rect.
        self.table.doItemsLayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'table'):
            # Type remains in product details; reserve visible space for actions.
            self.table.setColumnHidden(2, self.width() < 1000)
        if hasattr(self, 'bundle_table'):
            self.bundle_table.setColumnHidden(2, self.width() < 1000)

    @staticmethod
    def _title_key(title):
        return ''.join(c for c in str(title).casefold() if c.isalnum())

    @classmethod
    def _native_eligible(cls, product):
        return cls._title_key(product_values(product)[0]) in ('phasis', 'reaktor6', 'reaktor6fx')

    @classmethod
    def _artifact_matches(cls, artifact, product):
        if product.get('upid') and str(product['upid']) == str(artifact.upid):
            return True
        return cls._title_key(artifact.title) == cls._title_key(product_values(product)[0])

    def _sort_inline_installers(self, artifacts):
        def platform_rank(artifact):
            platform = artifact.platform.casefold()
            if platform.startswith('linux'):
                return 0 if self.settings.prefer_native else 1
            if platform == 'pc' or platform.startswith(('win', 'pc-')):
                return 1 if self.settings.prefer_native else 0
            return 2 if platform.startswith(('mac', 'osx')) else 3
        # Two stable sorts keep newest numeric versions within each platform
        # preference, including multi-digit versions such as 1.10 versus 1.7.
        newest = sorted(artifacts, key=lambda artifact: tuple(int(part) for part in re.findall(r'\d+', artifact.version)),
                        reverse=True)
        return sorted(newest, key=platform_rank)

    def download_product(self, product):
        if self._busy or not self._require_session():
            return
        if self.artifacts:
            self._show_download_picker(product)
            return
        from tux_access.downloads.catalog import available_artifacts
        token = self._token
        self._run('Reading installers for ' + product_values(product)[0] + '…',
                  lambda: {'artifacts': available_artifacts(token), 'product': product}, 'product_artifacts')

    def install_product(self, product):
        from tux_access.catalog.bundles import is_bundle
        if is_bundle(product):
            self.show_bundle(product)
            return
        if self._busy:
            return
        if not self._supported(product) or (product.get('bundleParentUpid') and not product.get('bundleInstallerAvailable')):
            self.open_install_options(product)
            return
        if not self._require_session():
            return
        from tux_access.installation.install import install_product
        token, settings, artifacts = self._token, self.settings, list(self.artifacts)
        self._active_product = product
        def operation():
            result = install_product(product, token, settings, artifacts=artifacts or None,
                                     progress=self._installation_progress, cancelled=self._cancel.is_set)
            return self._post_install_scan(result, settings)
        self._run('Preparing ' + product_values(product)[0] + '…',
                  operation,
                  'install', download=True, retry=lambda: self.install_product(product))

    def _installation_progress(self, stage, current=0, total=None, message=''):
        self._events.put(('stage', {'stage': stage, 'current': current, 'total': total,
                                    'message': message}))

    def _post_install_scan(self, result, settings):
        from tux_access.installation.install import installed_catalog
        try:
            result['_installed'] = installed_catalog(settings)
        except Exception as error:
            # The backend has already committed successfully; a failed UI scan
            # must not turn that result into an installation failure or retry.
            result['_scan_warning'] = self._safe_message(str(error))
        return result

    def details(self):
        from tux_access.catalog.bundles import is_bundle
        product = self._selected_product()
        self.product_options_button.setText('View products' if product is not None and is_bundle(product) else 'Installation options')
        self.product_options_button.setEnabled(product is not None and not self._busy and self._login_banner is None)
        removable = self._removal_available(product)
        self.uninstall_button.setEnabled(removable and not self._busy and self._login_banner is None)
        self.uninstall_button.setToolTip('Remove the selected app files while retaining saved projects, content and settings.' if removable else
                                         'Removal is limited to qualified launcher-owned packages and managed Wine installations; legacy experiments are retained.')
        if product is not None:
            self._selected_identity = self._product_key(product)
            title, version, kind, state = product_values(product)
            state = self._product_states.get(self._product_key(product), state)
            lines = [f'Product: {title}', f'Version: {version}', f'Type: {kind}', f'State: {state}']
            lines.append('Installation: automatic download → checksum verification → file installation' if self._supported(product) else
                         self._unsupported_reason(product))
            lines.append('NI license activation: unverified')
            if product.get('backend') == 'wine':
                lines.append('Installation source: ' + str(product.get('source') or 'unverified catalog record'))
                if type(product.get('managed')) is bool:
                    lines.append('Managed prefix: ' + ('yes' if product['managed'] else 'no · verified prior experiment'))
                if product.get('prefix'):
                    lines.append('Wine prefix: ' + str(product['prefix']))
            if product.get('vendor'):
                lines.append('Vendor: ' + str(product['vendor']))
            if product.get('platforms'):
                lines.append('Platforms: ' + ', '.join(product['platforms']))
            if product.get('binaryPath'):
                lines.append('Executable: ' + product['binaryPath'])
            for component in product.get('components', []):
                label = {1: 'Install location', 2: 'Content location'}.get(component.get('name'), 'Component location')
                lines.append(label + ': ' + component.get('currentPath', ''))
            self.detail.setPlainText('\n'.join(lines))

    def _unsupported_reason(self, product):
        from tux_access.catalog.bundles import is_bundle
        title = product_values(product)[0]
        if is_bundle(product):
            return title + ' is a collection with no single application installer. Choose View products to inspect its confirmed members and install individual supported products.'
        return title + ' installation is not available yet. Supported workflows are Phasis, Reaktor 6, Kontakt 8.9.0, Maschine 2.18.4 and Massive 1.7.0. Advanced tools provides manual downloads and inspection.'

    def open_selected_options(self):
        from tux_access.catalog.bundles import is_bundle
        product = self._selected_product()
        if product is not None and not self._busy:
            if is_bundle(product):
                self.show_bundle(product)
            else:
                self.open_install_options(product)

    def open_install_options(self, product):
        if self._busy:
            return
        self._selected_identity = self._product_key(product)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.data(int(QtCore.Qt.ItemDataRole.UserRole) + 1) == self._selected_identity:
                self.table.setCurrentCell(row, 0)
                self.table.selectRow(row)
                break
        self.show_settings(product=product, advanced=True)
        self.status.setText(self._bundle_reason(product) if product.get('bundleParentUpid') else self._unsupported_reason(product) if not self._supported(product) else
                            'Installation options for ' + product_values(product)[0] + '. Downloads alone do not establish activation or installation support.')
        if self._token:
            self.load_inline_installers()

    def account_clicked(self):
        if self._busy:
            return
        if self._token:
            self.account_menu.popup(self.sign_in_button.mapToGlobal(self.sign_in_button.rect().bottomLeft()))
        else:
            self.sign_in()

    def _update_account_button(self):
        self.switch_account_action.setEnabled(bool(self._token) and not self._busy)
        self.sign_out_action.setEnabled(bool(self._token) and not self._busy)
        if self._token:
            name = self._profile.get('given_name') or self._profile.get('name') or ''
            initial = next((letter.upper() for letter in str(name).strip() if letter.isalpha()), 'A')
            self.sign_in_button.setObjectName('account')
            self.sign_in_button.setText(initial)
            self.sign_in_button.setFixedSize(40, 40)
            self.sign_in_button.setToolTip('Account · switch account or sign out')
            self.sign_in_button.setAccessibleName('Account menu')
        else:
            self.sign_in_button.setObjectName('primary')
            self.sign_in_button.setText('Sign in')
            self.sign_in_button.setMinimumSize(0, 0)
            self.sign_in_button.setMaximumSize(16777215, 16777215)
            self.sign_in_button.setToolTip('Sign in with Native Instruments')
            self.sign_in_button.setAccessibleName('Sign in')
        self.sign_in_button.style().unpolish(self.sign_in_button)
        self.sign_in_button.style().polish(self.sign_in_button)
        self.sign_in_button.updateGeometry()

    def sign_out(self):
        if self._busy:
            return
        if self._login_banner is not None:
            self._login_banner.reject()
        self._token = self._refresh_token = None
        self._account_records = []
        self._profile = {}
        self._options_product = None
        self._inline_artifacts = []
        self.artifacts = []
        self._verified_files.clear()
        self._verified_artifacts.clear()
        self._product_states.clear()
        self._retry = None
        self._active_product = None
        self._selected_identity = None
        self._events = queue.Queue()
        self.products = list(self._local_records)
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.retry_button.hide()
        self.account_status.setText('Account not connected')
        self._update_account_button()
        self.set_view('all')
        self._bundle_product = None
        self._render_bundle()
        self.status.setText('Signed out. Local installations and settings are retained.')

    def _run(self, title, operation, kind, download=False, retry=None):
        if self._busy or self._login_banner is not None:
            return
        self.cancel_uninstall_confirmation(announce=False)
        self._busy = True
        self._retry = retry
        self._cancel.clear()
        self.retry_button.hide()
        self.status.setText(title)
        for button in self.actions + self.product_actions + self._bundle_actions:
            button.setEnabled(False)
        if self._bundle_page is not None:
            self.bundle_refresh_button.setEnabled(False)
        self.product_options_button.setEnabled(False)
        self.uninstall_button.setEnabled(False)
        self.switch_account_action.setEnabled(False)
        self.sign_out_action.setEnabled(False)
        for control in self._settings_controls:
            control.setEnabled(False)
        self.cancel_button.setEnabled(download)
        self.progress.setRange(0, 100 if download else 0)
        self.progress.setFormat('%p%' if download else 'Working…')
        self.progress.setValue(0)
        credentials = (self._token, self._refresh_token)
        def worker():
            try:
                self._events.put((kind, operation()))
            except Exception as error:
                # HTTP errors from adapters are redacted; never show token values.
                from tux_access.downloads.manager import DownloadCancelled
                event_kind = 'cancelled' if isinstance(error, DownloadCancelled) or self._cancel.is_set() else 'error'
                message = self._safe_message(str(error), credentials)
                if kind == 'uninstall':
                    try:
                        from tux_access.installation.install import installed_catalog
                        records = installed_catalog(self.settings)
                    except Exception:
                        records = None
                    self._events.put(('uninstall_failure', {'message': message, 'cancelled': event_kind == 'cancelled', '_installed': records}))
                else:
                    self._events.put((event_kind, message))
        threading.Thread(target=worker, daemon=True).start()

    def _safe_message(self, message, credentials=()):
        for credential in (self._token, self._refresh_token, *credentials):
            if credential:
                message = message.replace(credential, '[private account value]')
        return re.sub(r'https?://\S+', '[private request URL]', message)

    def _merge_installed(self, records=None):
        if records is not None:
            self._local_records = records
        records = self._local_records
        for native in records:
            matches = [p for p in self.products if self._installation_key(p) == self._installation_key(native)]
            if not matches:
                self.products.append(native)
            for match in matches:
                match.update({k: v for k, v in native.items() if k in ('version', 'type', 'status', 'source', 'nativePackage', 'backend',
                                                                    'prefix', 'executable', 'receipt', 'managed', 'binaryPath')})
                # Daemon installed flags must not hide the validated local file state.
                match.pop('installationState', None)
                match.pop('installationStatus', None)
                match.pop('installedVersion', None)
                if native.get('backend') == 'wine':
                    match['_local_installation'] = {key: value for key, value in native.items()
                                                    if key in ('title', 'version', 'backend', 'prefix', 'executable', 'receipt',
                                                               'managed', 'source', 'activation', 'installed')}
        return records

    def poll(self):
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            picker_product = None
            refresh_account = False
            if kind == 'progress':
                current, total = value
                self.progress.setValue(int(current * 100 / total) if total else 0)
                continue
            if kind == 'stage':
                stage = str(value['stage'])
                message = self._safe_message(value.get('message') or stage.replace('_', ' ').capitalize() + '…')
                self.status.setText(message)
                total, current = value.get('total'), value.get('current', 0)
                self.progress.setRange(0, 100 if total else 0)
                if total:
                    self.progress.setValue(int(current * 100 / total))
                self.progress.setFormat(stage.replace('_', ' ').capitalize() + (' · %p%' if total else '…'))
                self.cancel_button.setEnabled(not self._cancel.is_set() and stage not in ('native_install', 'pacman', 'install_native', 'removing', 'complete'))
                if self._active_product:
                    key = self._product_key(self._active_product)
                    label = stage.replace('_', ' ').capitalize()
                    if self._product_states.get(key) != label:
                        self._product_states[key] = label
                        self.render()
                continue
            if kind == 'catalog_ready':
                # Optional userinfo can be unavailable or slow. Publish the
                # valid library before finishing that in-memory account lookup.
                self._load_account_rows(value['catalog'])
                self._merge_installed(value['installed'])
                self.artifacts = value.get('artifacts', [])
                self._product_states = {}
                self.render()
                self.status.setText(value.get('artifact_warning') or
                                    ('Library loaded. Finishing the optional account display name lookup…' if value.get('metadata_ready') else
                                     'Library loaded. Reading authorized application installers…'))
                continue
            if kind == 'daemon':
                products, version, self._token = value
                self._load_account_rows(products)
                self._refresh_token = None
                self._profile = {}
                self.artifacts = []
                self.render()
                version_text = '.'.join(str(version[k]) for k in ('major', 'minor', 'micro'))
                self.status.setText(f'{len(self.products)} daemon products · NTK {version_text} · ' +
                                    ('Existing account session available in memory.' if self._token else 'No existing account session available.'))
                self.account_status.setText('Account connected' if self._token else 'Account not connected')
                self._update_account_button()
                refresh_account = bool(self._token)
            elif kind == 'local_catalog':
                if self._account_records is not None:
                    self.products = [dict(product) for product in self._account_records]
                else:
                    self.products = [product for product in self.products if product.get('upid') or
                                     not any(self._installation_key(product) == self._installation_key(local) for local in self._local_records)]
                self._product_states.clear()
                self._inventory_unknown = False
                records = self._merge_installed(value)
                self.status.setText(f'{len(records)} local installations checked. Sign in to load your account library.' if not self._token else
                                    f'{len(records)} local installations checked.')
                if self._settings_warning:
                    self.status.setText(self._safe_message(self._settings_warning))
            elif kind == 'catalog':
                self._load_account_rows(value['catalog'])
                account_count = len(self.products)
                records = self._merge_installed(value['installed'])
                self._profile = value.get('profile', {})
                self.artifacts = value.get('artifacts', [])
                self._update_account_button()
                self._product_states = {}
                self.render()
                message = f'{account_count} account products loaded · {len(records)} local installations. Choose Install to begin.'
                self.status.setText(message + (' ' + value['artifact_warning'] if value.get('artifact_warning') else ''))
            elif kind == 'login':
                self._token = value['access_token']
                self._refresh_token = value.get('refresh_token')
                self._profile = {}
                self.artifacts = []
                # A newly authorized account must not inherit the previous account's library.
                self._account_records = []
                self.products = list(self._local_records)
                self._product_states = {}
                self.account_status.setText('Signed in · session in memory')
                self._update_account_button()
                self.status.setText('Signed in. Loading your library…')
                refresh_account = True
            elif kind == 'artifacts':
                self.artifacts = value
                linux = sum(a.platform.startswith('linux') for a in value)
                self.status.setText(f'{len(value)} installer records loaded · {linux} Linux records. Use Settings → Advanced tools to choose an installer.')
            elif kind == 'inline_artifacts':
                self.artifacts = value['artifacts']
                if self._options_product is not None and self._product_key(self._options_product) == value['product_key']:
                    matches = [artifact for artifact in self.artifacts if self._artifact_matches(artifact, self._options_product)]
                    matches = self._sort_inline_installers(matches)
                    self._inline_artifacts = matches
                    self.inline_installer_table.setRowCount(len(matches))
                    for row, artifact in enumerate(matches):
                        for column, item in enumerate((artifact.version, artifact.platform, artifact.target_file, artifact.filesize)):
                            self.inline_installer_table.setItem(row, column, QtWidgets.QTableWidgetItem(str(item)))
                    if matches:
                        self.inline_installer_table.setCurrentCell(0, 0)
                        self.inline_installer_table.selectRow(0)
                    self.status.setText(f'{len(matches)} authorized installer choices. Select one to download and verify; unsupported installation remains unavailable.' if matches else
                                        'No authorized installer matched this product. Unsupported installation remains unavailable.')
            elif kind == 'product_artifacts':
                self.artifacts = value['artifacts']
                picker_product = value['product']
            elif kind == 'download':
                if value.get('artifact') is not None:
                    self._verified_artifacts[str(Path(value['path']).resolve())] = value['artifact']
                self.progress.setValue(100)
                self._verified_files[str(Path(value['path']).resolve())] = value['sha256']
                self.status.setText(f"Verified download saved: {value['path']}")
            elif kind == 'package':
                metadata = value['control']
                lines = [f"Package: {metadata.get('Package', '')}", f"Version: {metadata.get('Version', '')}",
                         f"Architecture: {metadata.get('Architecture', '')}", f"SHA-256: {value['sha256']}",
                         f"Pre-install requirements: {metadata.get('Pre-Depends', 'none declared')}",
                         f"Dependencies: {metadata.get('Depends', 'none declared')}",
                         f"Matches verified download: {'yes' if value['integrity_verified'] else 'not checked'}",
                         'Package code executed: no']
                for elf in value['elf_files']:
                    lines += ['', f"ELF file: {elf['path']}", f"Entry points: {', '.join(elf.get('plugin_entrypoints', []))}",
                              'Dependencies: ' + ', '.join(elf.get('needed_libraries', []))]
                self.detail.setPlainText('\n'.join(lines))
                self.status.setText('Package inspected. No installation or executable launch performed.')
            elif kind == 'install':
                if value.get('path') and value.get('sha256'):
                    canonical = str(Path(value['path']).resolve())
                    self._verified_files[canonical] = value['sha256']
                    if value.get('artifact'):
                        self._verified_artifacts[canonical] = value['artifact']
                self._merge_installed(value.get('_installed'))
                if self._active_product:
                    self._product_states[self._product_key(self._active_product)] = 'Installed · activation unverified'
                    self._active_product.update(status='Installed · activation unverified', version=value['version'])
                    if value.get('backend'):
                        self._active_product['backend'] = value['backend']
                self.render()
                self.status.setText(f"{value['title']} {value['version']} files installed. NI activation remains unverified.")
                if value.get('_scan_warning'):
                    self.status.setText(self.status.text() + ' Local catalog check needs attention: ' + value['_scan_warning'])
                self.progress.setValue(100)
                self._retry = None
            elif kind == 'uninstall':
                target = self._canonical_local_record(self._active_product) if self._active_product is not None else value
                self._rebuild_after_removal(value.get('_installed'), target)
                text = value['title'] + ' app files uninstalled. Saved projects, content and settings were retained.'
                if value.get('retained_directory'):
                    text += ' Retained data: ' + str(value['retained_directory'])
                if value.get('_installed') is not None and any(self._installation_key(record) == self._installation_key(target)
                                                             and self._installed_locally(record) for record in self._local_records):
                    text += ' Another verified installation remains available; its source is shown in product details.'
                if value.get('_scan_warning'):
                    text += ' ' + str(value['_scan_warning'])
                self.status.setText(self._safe_message(text))
                self.progress.setValue(100)
                self._retry = None
            elif kind == 'uninstall_failure':
                target = self._canonical_local_record(self._active_product) if self._active_product is not None else {}
                records = value.get('_installed')
                if records is not None:
                    self._rebuild_after_removal(records, target)
                else:
                    self._inventory_unknown = True
                    self._product_states.clear()
                    for product in self.products:
                        if self._installation_key(product) == self._installation_key(target):
                            self._product_states[self._product_key(product)] = 'Installation state needs refresh'
                self.status.setText(('Uninstall cancelled: ' if value.get('cancelled') else 'Uninstall failed: ') + value['message'] +
                                    (' Refresh the library to verify the current application state.' if records is None else ' The library now shows the verified remaining files.'))
                retry_product = next((product for product in self.products if self._installation_key(product) == self._installation_key(target)), None)
                self._retry = (lambda product=retry_product: self.request_uninstall(product)) if self._removal_available(retry_product) else None
                self.retry_button.setVisible(self._retry is not None)
            elif kind == 'wine_diagnostics':
                lines = ['Managed Wine diagnostics', 'Prefix: ' + value.get('prefix', ''),
                         'Installation: ' + value.get('installation', {}).get('status', 'unknown'),
                         'NI activation: unverified', '']
                for check in value.get('diagnostics', []):
                    lines.append(check.get('status', '').upper() + ' · ' + check.get('message', ''))
                    if check.get('action'):
                        lines.append('Next step: ' + check['action'])
                self.detail.setPlainText(self._safe_message('\n'.join(lines)))
                self.status.setText('Wine diagnostics complete. Review the checks and next steps below.')
            elif kind == 'launch':
                self.status.setText(str(value.get('title', 'Application')) + ' process started. This does not establish activation or audio compatibility.')
            elif kind in ('error', 'cancelled'):
                self.status.setText(('Cancelled: ' if kind == 'cancelled' else 'Operation failed: ') + value)
                if self._active_product:
                    self._product_states[self._product_key(self._active_product)] = 'Cancelled' if kind == 'cancelled' else 'Failed'
                self.retry_button.setVisible(self._retry is not None)
            self._busy = False
            self.progress.setRange(0, 100)
            self.progress.setFormat({'download': 'Download verified', 'install': 'Files installed', 'uninstall': 'Uninstalled',
                                     'uninstall_failure': 'Removal needs attention', 'error': 'Failed', 'cancelled': 'Cancelled'}.get(kind, 'Idle'))
            self.cancel_button.setEnabled(False)
            self._active_product = None
            for button in self.actions + self.product_actions:
                button.setEnabled(True)
            self.switch_account_action.setEnabled(bool(self._token))
            self.sign_out_action.setEnabled(bool(self._token))
            for control in self._settings_controls:
                control.setEnabled(True)
            detail_report = self.detail.toPlainText() if kind in ('package', 'wine_diagnostics') else None
            self.render()
            if detail_report is not None:
                self.detail.setPlainText(detail_report)
            if self._closing:
                self.close()
            elif kind == 'product_artifacts':
                self._show_download_picker(picker_product)
            elif refresh_account:
                self.account_catalog()

    def connect_daemon(self):
        self._run('Reading existing NTK daemon and account session…', lambda: daemon_snapshot(self.endpoint), 'daemon')

    def sign_in(self):
        if self._busy:
            return
        self.cancel_uninstall_confirmation(announce=False)
        if self._login_banner is not None:
            self.sign_in_area.show()
            return
        try:
            from tux_access.auth.login import login_banner
            banner = login_banner(self, force_login=bool(self._token))
        except ImportError:
            self.status.setText('Sign-in requires Qt desktop components; install the desktop extra.')
            return
        self._login_banner = banner
        self.sign_in_layout.addWidget(banner)
        self.sign_in_area.show()
        banner.show()
        banner.finished.connect(lambda result: self._finish_sign_in(banner, result))
        for button in self.actions + self.product_actions + self._bundle_actions + self._settings_controls:
            button.setEnabled(False)
        self.switch_account_action.setEnabled(False)
        self.sign_out_action.setEnabled(False)
        self.product_options_button.setEnabled(False)
        self.uninstall_button.setEnabled(False)
        self.status.setText('Complete sign-in in your browser, or cancel using the banner above.')
        banner.start()

    def _finish_sign_in(self, banner, result):
        if banner is not self._login_banner:
            return
        code, verifier, redirect_uri = banner.code, banner.verifier, banner.redirect_uri
        banner.code = banner.verifier = None
        self._login_banner = None
        self.sign_in_layout.removeWidget(banner)
        banner.hide()
        banner.deleteLater()
        self.sign_in_area.hide()
        for button in self.actions + self._settings_controls:
            button.setEnabled(True)
        self._update_account_button()
        self.render()
        if result != 1 or not code or not verifier:
            self.status.setText('Sign-in cancelled. Your existing session is unchanged.' if self._token else 'Sign-in cancelled.')
            return
        from tux_access.auth.oauth import exchange_code
        from tux_access.auth.transport import AuthHttpTransport
        self._run('Finishing secure account authorization…',
                  lambda: exchange_code(code, verifier, AuthHttpTransport(), redirect_uri), 'login')

    def _require_session(self):
        if not self._token:
            self.status.setText('Sign in first, or connect an existing account session.')
            return False
        return True

    def account_catalog(self):
        if not self._token:
            self.refresh_local_installations()
            return
        if self._require_session():
            from tux_access.auth.api import catalog
            from tux_access.installation.install import installed_catalog
            token, settings = self._token, self.settings
            def operation():
                result = {'catalog': catalog(token), 'installed': installed_catalog(settings)}
                self._events.put(('catalog_ready', dict(result)))
                try:
                    from tux_access.downloads.catalog import available_artifacts
                    from tux_access.catalog.applications import expand_catalog
                    artifacts = available_artifacts(token)
                    expanded = expand_catalog(result['catalog'], artifacts)
                    result.update(catalog=expanded, artifacts=artifacts)
                except Exception:
                    # Installer discovery is optional. Do not expose request
                    # URLs or discard valid account entitlements on failure.
                    result.update(artifacts=[], artifact_warning='Application installer metadata is unavailable. Account products remain visible; bundle applications may be missing. Refresh to try again.')
                result['metadata_ready'] = True
                self._events.put(('catalog_ready', dict(result)))
                try:
                    from tux_access.auth.profile import profile
                    result['profile'] = {key: value for key, value in profile(token).items()
                                         if key in ('name', 'given_name') and isinstance(value, str)}
                except Exception:
                    # An optional account initial must never discard a valid catalog.
                    result['profile'] = {}
                return result
            self._run('Reading account catalog…', operation,
                      'catalog', retry=self.account_catalog)

    def wine_diagnostics(self):
        from tux_access.installation.wine.kontakt import WineManager
        settings = self.settings
        self._run('Checking Wine and managed installation requirements…', lambda: WineManager(settings).diagnose(),
                  'wine_diagnostics', retry=self.wine_diagnostics)

    def launch_kontakt(self, product=None):
        self.launch_wine_product(product)

    def launch_wine_product(self, product=None):
        if self._busy:
            return
        settings = self.settings
        record = product or next((p for p in self._local_records if p.get('backend') == 'wine' and self._installed_locally(p)), None)
        if record is None:
            self.status.setText('No verified local application is available to launch.')
            return
        record = self._canonical_local_record(record)
        from tux_access.installation.backends import wine_spec
        spec = wine_spec(record)
        if spec is None:
            self.status.setText('Launch is not available for ' + product_values(record)[0] + '. No qualified application profile matches this installation.')
            return
        title = record['title']
        self._run('Starting ' + title + '…', lambda: {'pid': spec.manager(settings).launch_record(record).pid, 'title': title},
                  'launch', retry=lambda: self.launch_wine_product(record))

    def artifact_metadata(self):
        if self._require_session():
            from tux_access.downloads.catalog import available_artifacts
            token = self._token
            self._run('Reading authorized artifact metadata…', lambda: available_artifacts(token), 'artifacts')

    def show_settings(self, product=None, advanced=False):
        """Edit non-secret preferences inside the main window."""
        self.cancel_uninstall_confirmation(announce=False)
        from dataclasses import replace
        from tux_access.settings import save_settings, validate_settings
        if not isinstance(product, dict):
            product = None
        if self._settings_page is not None and self.pages.currentWidget() == self._settings_page:
            return
        if self._settings_page is not None:
            self.pages.removeWidget(self._settings_page)
            self._settings_page.deleteLater()
        page = QtWidgets.QWidget()
        page.setObjectName('settingsPage')
        self._settings_page = page
        self._settings_controls = []
        self._options_product = product
        self._inline_artifacts = []
        self.pages.addWidget(page)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QtWidgets.QLabel('Settings')
        heading.setObjectName('title')
        layout.addWidget(heading)
        introduction = QtWidgets.QLabel('Paths and preferences apply to future operations. Account credentials are never saved.')
        introduction.setWordWrap(True)
        introduction.setObjectName('muted')
        layout.addWidget(introduction)
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs, 1)
        general = QtWidgets.QWidget()
        general.setObjectName('settingsContents')
        form = QtWidgets.QFormLayout(general)
        form.setContentsMargins(18, 22, 18, 18)
        form.setVerticalSpacing(14)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        fields = {}
        for key, label in [('download_directory', 'Downloads'), ('installation_directory', 'Application storage'),
                           ('content_directory', 'Content (reserved)'), ('wine_prefix_directory', 'Wine prefix base'),
                           ('yabridge_directory', 'yabridge directory (optional)')]:
            row = QtWidgets.QWidget()
            horizontal = QtWidgets.QHBoxLayout(row)
            horizontal.setContentsMargins(0, 0, 0, 0)
            value = getattr(self.settings, key)
            edit = QtWidgets.QLineEdit(str(value) if value else '')
            horizontal.addWidget(edit, 1)
            form.addRow(label, row)
            fields[key] = edit
            self._settings_controls.append(edit)
        self._settings_fields = fields
        wine_command = QtWidgets.QLineEdit(self.settings.wine_executable)
        self._settings_controls.append(wine_command)
        form.addRow('Wine executable', wine_command)
        toggles = {}
        for key, label in [('prefer_native', 'Prefer supported native Linux installers'),
                           ('manage_wine', 'Enable managed Wine installation'),
                           ('manual_mode', 'Show advanced manual controls by default')]:
            checkbox = QtWidgets.QCheckBox(label)
            checkbox.setChecked(getattr(self.settings, key))
            toggles[key] = checkbox
            form.addRow(checkbox)
            self._settings_controls.append(checkbox)
        note = QtWidgets.QLabel('Native Arch VST packages use fixed system plug-in paths. Application storage does not relocate those files. The content path is reserved for future library installers. Wine adapters accept exact Kontakt 8.9.0, Maschine 2.18.4 and Massive 1.7.0 installers; activation is unverified. Maschine libraries and controller support are separate.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        form.addRow(note)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName('settingsScroll')
        scroll.viewport().setObjectName('settingsViewport')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(general)
        tabs.addTab(scroll, 'Installation')
        advanced_contents = QtWidgets.QWidget()
        advanced_contents.setObjectName('settingsContents')
        tools = QtWidgets.QVBoxLayout(advanced_contents)
        tools.setContentsMargins(18, 22, 18, 18)
        explanation = QtWidgets.QLabel('Manual tools expose installer choices and package inspection. They do not establish installation or activation support for other products.')
        explanation.setWordWrap(True)
        tools.addWidget(explanation)
        if product is not None:
            context = QtWidgets.QLabel('Install options · ' + product_values(product)[0])
            context.setStyleSheet('font-size:18px;font-weight:600')
            tools.addWidget(context)
            reason = QtWidgets.QLabel(self._bundle_reason(product) if product.get('bundleParentUpid') else self._unsupported_reason(product) if not self._supported(product) else
                                    'Use manual download and inspection for this product. Existing installed files are preserved; NI activation is unverified.')
            reason.setWordWrap(True)
            tools.addWidget(reason)
            load = QtWidgets.QPushButton('Load this product’s installer choices')
            load.clicked.connect(self.load_inline_installers)
            tools.addWidget(load)
            self._settings_controls.append(load)
            self.inline_installer_table = QtWidgets.QTableWidget(0, 4)
            self.inline_installer_table.setHorizontalHeaderLabels(['Version', 'Platform', 'Filename', 'Bytes'])
            self.inline_installer_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.inline_installer_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.inline_installer_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.inline_installer_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            self.inline_installer_table.verticalHeader().hide()
            self.inline_installer_table.setMinimumHeight(240)
            self.inline_installer_table.setMaximumHeight(320)
            tools.addWidget(self.inline_installer_table)
            self.inline_download_button = QtWidgets.QPushButton('Download selected installer')
            self.inline_download_button.clicked.connect(self.download_inline_installer)
            tools.addWidget(self.inline_download_button)
            self._settings_controls.append(self.inline_download_button)
            self.inline_download_button.setToolTip('Download and verify only. This does not install an unsupported product.')
        endpoint = QtWidgets.QLineEdit(self.endpoint)
        self._settings_controls.append(endpoint)
        tools.addWidget(QtWidgets.QLabel('Existing NTK reference session endpoint'))
        tools.addWidget(endpoint)
        advanced_methods = [('Connect existing session', self.connect_daemon),
                            ('Import product catalog…', self.import_catalog), ('Export product catalog…', self.export_catalog),
                            ('Refresh artifact metadata', self.artifact_metadata), ('Choose and download installer…', self.choose_download),
                            ('Inspect Linux package…', self.inspect_package), ('Install verified Linux package…', self.install_linux_package),
                            ('Wine diagnostics', self.wine_diagnostics)]
        grid = QtWidgets.QGridLayout()
        tools.addLayout(grid)
        for index, (text, method) in enumerate(advanced_methods):
            button = QtWidgets.QPushButton(text)
            button.setEnabled(not self._busy)
            def dispatch(checked=False, action=method):
                self.set_view(self._view)
                action()
            button.clicked.connect(dispatch)
            grid.addWidget(button, index // 2, index % 2)
            self._settings_controls.append(button)
        tools.addStretch()
        privacy = QtWidgets.QLabel('Only paths and preferences are saved. Account tokens and browser callbacks remain private and transient. Product exports contain catalog data; signed download URLs are excluded.')
        privacy.setWordWrap(True)
        privacy.setObjectName('muted')
        tools.addWidget(privacy)
        advanced_scroll = QtWidgets.QScrollArea()
        advanced_scroll.setObjectName('settingsScroll')
        advanced_scroll.viewport().setObjectName('settingsViewport')
        advanced_scroll.setWidgetResizable(True)
        advanced_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        advanced_scroll.setWidget(advanced_contents)
        tabs.addTab(advanced_scroll, 'Advanced tools')
        notice = QtWidgets.QLabel('')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.settings_cancel_button = QtWidgets.QPushButton('Cancel')
        self.settings_cancel_button.setMinimumHeight(38)
        self.settings_save_button = QtWidgets.QPushButton('Save settings')
        self.settings_save_button.setMinimumHeight(38)
        self.settings_save_button.setObjectName('primary')
        buttons.addWidget(self.settings_cancel_button)
        buttons.addWidget(self.settings_save_button)
        self._settings_controls.append(self.settings_save_button)
        def save():
            try:
                changes = {key: Path(edit.text().strip()).expanduser() if edit.text().strip() else None for key, edit in fields.items()}
                changes.update({key: value.isChecked() for key, value in toggles.items()})
                changes.update(wine_executable=wine_command.text().strip(), reference_endpoint=endpoint.text().strip())
                settings = validate_settings(replace(self.settings, **changes))
                save_settings(settings)
            except (OSError, ValueError, TypeError) as error:
                notice.setText('Settings could not be saved: ' + self._safe_message(str(error)))
                return
            self.settings, self.endpoint = settings, settings.reference_endpoint
            self._settings_warning = None
            self.render()
            self.status.setText('Settings saved. New installations use these options.')
            self.set_view(self._view)
            self.refresh_local_installations()
        self.settings_save_button.clicked.connect(save)
        self.settings_cancel_button.clicked.connect(lambda: self.set_view(self._view))
        layout.addLayout(buttons)
        for control in self._settings_controls:
            control.setEnabled(not self._busy and self._login_banner is None)
        for button, _ in self.nav_buttons:
            button.setChecked(False)
        self.settings_button.setChecked(True)
        self.about_button.setChecked(False)
        self.pages.setCurrentWidget(page)
        if advanced or self.settings.manual_mode:
            tabs.setCurrentIndex(1)

    def load_inline_installers(self):
        if self._busy or self._options_product is None or not self._require_session():
            return
        from tux_access.downloads.catalog import available_artifacts
        token = self._token
        product = self._options_product
        def operation():
            from tux_access.downloads.manager import DownloadCancelled
            artifacts = available_artifacts(token)
            if self._cancel.is_set():
                raise DownloadCancelled('Installer lookup cancelled')
            return {'artifacts': artifacts, 'product_key': self._product_key(product)}
        self._run('Reading authorized installer choices…', operation, 'inline_artifacts', download=True,
                  retry=self.load_inline_installers)

    def download_inline_installer(self):
        if self._busy or self._options_product is None:
            return
        row = self.inline_installer_table.currentRow()
        if row < 0 or row >= len(self._inline_artifacts):
            self.status.setText('Select an installer from the inline choices first. This action downloads only.')
            return
        self.download_artifact(self._inline_artifacts[row], str(self.settings.download_directory))

    def import_catalog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import catalog', '', 'JSON catalog (*.json)')
        if path:
            try:
                self._load_account_rows(json.loads(Path(path).read_text(encoding='utf-8')))
                self.render()
                self.status.setText(f'Imported {len(self.products)} products.')
            except (OSError, ValueError) as error:
                self.status.setText('Import failed: ' + str(error))

    def export_catalog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export catalog', '', 'JSON catalog (*.json)')
        if path:
            try:
                # Deliberately export display metadata rather than arbitrary account/import fields.
                public = []
                for product in self.products:
                    title, version, kind, state = product_values(product)
                    record = {'title': title, 'version': version, 'type': kind, 'status': state}
                    if isinstance(product.get('upid'), str):
                        record['upid'] = product['upid']
                    if isinstance(product.get('platforms'), list):
                        record['platforms'] = [value for value in product['platforms'] if isinstance(value, str)]
                    public.append(record)
                Path(path).write_text(json.dumps({'products': public}, indent=2, ensure_ascii=False), encoding='utf-8')
                self.status.setText('Product catalog exported.')
            except OSError as error:
                self.status.setText('Export failed: ' + str(error))

    def choose_download(self):
        if not self._require_session():
            return
        if not self.artifacts:
            product = self._selected_product()
            if product is not None:
                self.download_product(product)
            else:
                from tux_access.downloads.catalog import available_artifacts
                token = self._token
                self._run('Reading authorized installer choices…',
                          lambda: {'artifacts': available_artifacts(token), 'product': None},
                          'product_artifacts')
            return
        product = self._selected_product()
        self._show_download_picker(product)

    def _show_download_picker(self, product=None):
        artifacts = [a for a in self.artifacts if product is None or self._artifact_matches(a, product)]
        if not artifacts:
            self.status.setText('No authorized installer metadata matched ' + (product_values(product)[0] if product else 'the selected product') + '.')
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Download ' + (product_values(product)[0] if product else 'artifact'))
        dialog.resize(980, 470)
        layout = QtWidgets.QVBoxLayout(dialog)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText('Filter by product, version, platform or filename')
        layout.addWidget(search)
        table = QtWidgets.QTableWidget(len(artifacts), 5)
        table.setHorizontalHeaderLabels(['Product', 'Version', 'Platform', 'Filename', 'Bytes'])
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        for row, artifact in enumerate(artifacts):
            for column, value in enumerate((artifact.title, artifact.version, artifact.platform, artifact.target_file, artifact.filesize)):
                table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
        layout.addWidget(table)
        def filter_rows(text):
            query = text.casefold()
            for row in range(table.rowCount()):
                values = ' '.join(table.item(row, col).text() for col in range(table.columnCount()))
                table.setRowHidden(row, query not in values.casefold())
        search.textChanged.connect(filter_rows)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or table.currentRow() < 0:
            return
        if table.isRowHidden(table.currentRow()):
            return
        artifact = artifacts[table.currentRow()]
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, 'Save verified artifact', str(self.settings.download_directory))
        if not directory:
            return
        self.download_artifact(artifact, directory)

    def download_artifact(self, artifact, directory):
        """Shared action for the picker and the end-to-end GUI verification."""
        if not self._require_session():
            return
        from tux_access.downloads.manager import resolve_artifact, download
        token = self._token
        def operation():
            spec = resolve_artifact(artifact, token)
            path = download(spec, directory, cancelled=self._cancel.is_set,
                            progress=lambda current, total: self._events.put(('progress', (current, total))))
            return {'path': str(path), 'sha256': spec.sha256, 'artifact': artifact}
        self._run('Resolving and downloading selected artifact…', operation, 'download', download=True,
                  retry=lambda: self.download_artifact(artifact, directory))

    def inspect_package(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Inspect Linux package', '', 'Debian package (*.deb)')
        if path:
            from tux_access.installation.native.inspection import inspect_deb
            canonical = str(Path(path).resolve())
            digest = self._verified_files.get(canonical)
            self._run('Inspecting Linux package…', lambda: inspect_deb(canonical, digest), 'package')

    def install_linux_package(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Install verified Linux package', '', 'Debian package (*.deb)')
        if not path:
            return
        canonical = str(Path(path).resolve())
        self._install_verified_path(canonical)

    def _install_verified_path(self, canonical):
        digest = self._verified_files.get(canonical)
        if not digest:
            self.status.setText('Download this package through the launcher first so its NI checksum can be verified.')
            return
        from tux_access.installation.native.arch import install_verified_vst
        settings = self.settings
        def operation():
            result = install_verified_vst(canonical, digest)
            return self._post_install_scan(result, settings)
        self._run('Preparing and installing the verified native VST payload…',
                  operation, 'install')

    def closeEvent(self, event):
        self._cancel.set()
        self._token = None
        self._refresh_token = None
        self._profile = {}
        if self._login_banner is not None:
            self._login_banner.reject()
        if self._busy:
            self._closing = True
            self.status.setText('Stopping active operation and cleaning up…')
            event.ignore()
            return
        self._verified_files.clear()
        self._verified_artifacts.clear()
        self.artifacts = []
        self._options_product = None
        self._inline_artifacts = []
        self._retry = None
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description='Independent native Qt launcher')
    parser.add_argument('--endpoint', default='tcp://127.0.0.1:5146')
    arguments = parser.parse_args()
    app = QtWidgets.QApplication([])
    window = Launcher(arguments.endpoint)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
