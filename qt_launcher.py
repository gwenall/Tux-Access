"""Native Qt launcher with account downloads and verified Linux installation."""
import argparse
import json
from pathlib import Path
import queue
import threading
from PySide6 import QtCore, QtWidgets
from launcher import catalog_rows, product_values


def daemon_snapshot(endpoint):
    from ntk_protocol import NtkClient, PROTOCOL_VERSION
    from schema_codec import encode, decode
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


class Launcher(QtWidgets.QMainWindow):
    def __init__(self, endpoint='tcp://127.0.0.1:5146'):
        super().__init__()
        self.endpoint = endpoint
        from arch_package import installed_products
        self.products, self.artifacts = installed_products(), []
        self._token = None
        self._refresh_token = None
        self._verified_files = {}
        self._verified_artifacts = {}
        self.product_actions = []
        self._events = queue.Queue()
        self._busy = False
        self._closing = False
        self._cancel = threading.Event()
        self.setWindowTitle('Native Access Linux 0.6.1 — Python proof of concept')
        screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 900)
        self.resize(min(1180, available.width() - 48), min(780, available.height() - 64))
        panel = QtWidgets.QWidget()
        self.setCentralWidget(panel)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QtWidgets.QLabel('Native Access Linux')
        heading.setStyleSheet('font-size:26px;font-weight:600')
        layout.addWidget(heading)
        layout.addWidget(QtWidgets.QLabel('Independent native Python launcher · NI account catalog'))
        toolbar = QtWidgets.QGridLayout()
        layout.addLayout(toolbar)
        self.actions = []
        for index, (text, method) in enumerate([('Sign in', self.sign_in), ('Connect existing session', self.connect_daemon), ('Import catalog', self.import_catalog),
                             ('Export catalog', self.export_catalog), ('Account catalog', self.account_catalog),
                             ('Artifact metadata', self.artifact_metadata), ('Download artifact', self.choose_download),
                             ('Inspect package', self.inspect_package), ('Install Linux package', self.install_linux_package)]):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(method)
            toolbar.addWidget(button, index // 4, index % 4)
            self.actions.append(button)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search products')
        self.search.textChanged.connect(self.render)
        layout.addWidget(self.search)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        layout.addWidget(split, 1)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Product', 'Version', 'Type', 'State', 'Actions'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.details)
        split.addWidget(self.table)
        self.detail = QtWidgets.QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        split.setSizes([430, 150])
        progress_row = QtWidgets.QHBoxLayout()
        layout.addLayout(progress_row)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat('Idle')
        progress_row.addWidget(self.progress, 1)
        self.cancel_button = QtWidgets.QPushButton('Cancel download')
        self.cancel_button.clicked.connect(self._cancel.set)
        self.cancel_button.setEnabled(False)
        progress_row.addWidget(self.cancel_button)
        self.status = QtWidgets.QLabel('Sign in to load your account catalog, or import a catalog.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        limitation = QtWidgets.QLabel('Native VST2 installation supports Phasis and Reaktor. NI activation is unverified.')
        limitation.setWordWrap(True)
        layout.addWidget(limitation)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(75)
        self.render()

    def render(self, *_):
        self.product_actions = []
        query = self.search.text().casefold()
        rows = [(i, p) for i, p in enumerate(self.products) if query in product_values(p)[0].casefold()]
        self.table.setRowCount(len(rows))
        for row, (index, product) in enumerate(rows):
            for column, value in enumerate(product_values(product)):
                item = QtWidgets.QTableWidgetItem(value)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, index)
                self.table.setItem(row, column, item)
            actions = QtWidgets.QWidget()
            buttons = QtWidgets.QHBoxLayout(actions)
            buttons.setContentsMargins(4, 2, 4, 2)
            for label, callback in (('Download', self.download_product), ('Install', self.install_product)):
                button = QtWidgets.QPushButton(label)
                button.setEnabled(not self._busy)
                button.clicked.connect(lambda checked=False, p=product, action=callback: action(p))
                button.setToolTip('Choose this product’s authorized installer.' if label == 'Download' else
                                  ('Install a Linux package verified by this launcher.' if self._native_eligible(product) else
                                   'Native installation supports Phasis and Reaktor 6; Windows/Wine installation is not available yet.'))
                buttons.addWidget(button)
                self.product_actions.append(button)
            self.table.setCellWidget(row, 4, actions)

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

    def download_product(self, product):
        if self._busy or not self._require_session():
            return
        if self.artifacts:
            self._show_download_picker(product)
            return
        from download_catalog import available_artifacts
        token = self._token
        self._run('Reading installers for ' + product_values(product)[0] + '…',
                  lambda: {'artifacts': available_artifacts(token), 'product': product}, 'product_artifacts')

    def install_product(self, product):
        if self._busy:
            return
        if not self._native_eligible(product):
            self.status.setText('Native installation currently supports Phasis and Reaktor 6. Windows/Wine installation is not available yet; you can download this product’s installer.')
            return
        matches = [(path, artifact) for path, artifact in self._verified_artifacts.items()
                   if self._artifact_matches(artifact, product) and artifact.platform.startswith('linux')
                   and artifact.target_file.lower().endswith('.deb') and path in self._verified_files]
        if not matches:
            self.status.setText('Download this product’s Linux .deb with its Download button first. Install requires a checksum-verified download from this launcher session.')
            return
        # Most recently verified matching download; installer rechecks its digest.
        self._install_verified_path(matches[-1][0])

    def details(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item is not None:
            product = self.products[item.data(QtCore.Qt.ItemDataRole.UserRole)]
            title, version, kind, state = product_values(product)
            lines = [f'Product: {title}', f'Version: {version}', f'Type: {kind}', f'State: {state}']
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

    def _run(self, title, operation, kind, download=False):
        if self._busy:
            return
        self._busy = True
        self._cancel.clear()
        self.status.setText(title)
        for button in self.actions + self.product_actions:
            button.setEnabled(False)
        self.cancel_button.setEnabled(download)
        self.progress.setRange(0, 100 if download else 0)
        self.progress.setFormat('%p%' if download else 'Working…')
        self.progress.setValue(0)
        def worker():
            try:
                self._events.put((kind, operation()))
            except Exception as error:
                # HTTP errors from adapters are redacted; never show token values.
                self._events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            picker_product = None
            if kind == 'progress':
                current, total = value
                self.progress.setValue(int(current * 100 / total) if total else 0)
                continue
            if kind == 'daemon':
                self.products, version, self._token = value
                self._refresh_token = None
                self.artifacts = []
                self.render()
                version_text = '.'.join(str(version[k]) for k in ('major', 'minor', 'micro'))
                self.status.setText(f'{len(self.products)} daemon products · NTK {version_text} · ' +
                                    ('Existing account session available in memory.' if self._token else 'No existing account session available.'))
            elif kind == 'catalog':
                self.products = catalog_rows(value)
                account_count = len(self.products)
                from arch_package import installed_products
                for native in installed_products():
                    match = next((p for p in self.products if product_values(p)[0].casefold() == native['title'].casefold()), None)
                    if match is not None:
                        match.update(version=native['version'], type=native['type'], status=native['status'])
                    else:
                        self.products.append(native)
                self.render()
                self.status.setText(f'{account_count} account products loaded · {len(installed_products())} native installations.')
            elif kind == 'login':
                self._token = value['access_token']
                self._refresh_token = value.get('refresh_token')
                self.artifacts = []
                self.status.setText('Signed in. Load the account catalog or artifact metadata.')
            elif kind == 'artifacts':
                self.artifacts = value
                linux = sum(a.platform.startswith('linux') for a in value)
                self.status.setText(f'{len(value)} artifact records loaded · {linux} Linux records. Choose Download artifact to inspect targets.')
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
                from arch_package import installed_products
                for native in installed_products():
                    match = next((p for p in self.products if self._title_key(product_values(p)[0]) ==
                                  self._title_key(native['title'])), None)
                    if match is None:
                        self.products.append(native)
                    else:
                        match.update(version=native['version'], type=native['type'], status=native['status'])
                self.render()
                self.status.setText(f"{value['title']} {value['version']} files installed. NI activation remains unverified.")
            elif kind == 'error':
                self.status.setText('Operation failed: ' + value)
            self._busy = False
            self.progress.setRange(0, 100)
            self.progress.setFormat('Download verified' if kind == 'download' else 'Idle')
            self.cancel_button.setEnabled(False)
            for button in self.actions + self.product_actions:
                button.setEnabled(True)
            if self._closing:
                self.close()
            elif picker_product is not None:
                self._show_download_picker(picker_product)

    def connect_daemon(self):
        self._run('Reading existing NTK daemon and account session…', lambda: daemon_snapshot(self.endpoint), 'daemon')

    def sign_in(self):
        try:
            from oauth_login import login_dialog
            dialog = login_dialog(self)
        except ImportError:
            self.status.setText('Sign-in requires Qt desktop components; install the desktop extra.')
            return
        dialog.start()
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        code, verifier, redirect_uri = dialog.code, dialog.verifier, dialog.redirect_uri
        dialog.code = None
        dialog.verifier = None
        dialog.deleteLater()
        from account_auth import exchange_code
        from auth_transport import AuthHttpTransport
        self._run('Finishing secure account authorization…',
                  lambda: exchange_code(code, verifier, AuthHttpTransport(), redirect_uri), 'login')

    def _require_session(self):
        if not self._token:
            self.status.setText('Sign in first, or connect an existing account session.')
            return False
        return True

    def account_catalog(self):
        if self._require_session():
            from account_api import catalog
            token = self._token
            self._run('Reading account catalog…', lambda: catalog(token), 'catalog')

    def artifact_metadata(self):
        if self._require_session():
            from download_catalog import available_artifacts
            token = self._token
            self._run('Reading authorized artifact metadata…', lambda: available_artifacts(token), 'artifacts')

    def import_catalog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import catalog', '', 'JSON catalog (*.json)')
        if path:
            try:
                self.products = catalog_rows(json.loads(Path(path).read_text(encoding='utf-8')))
                self.render()
                self.status.setText(f'Imported {len(self.products)} products.')
            except (OSError, ValueError) as error:
                self.status.setText('Import failed: ' + str(error))

    def export_catalog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export catalog', '', 'JSON catalog (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps({'products': self.products}, indent=2, ensure_ascii=False), encoding='utf-8')
                self.status.setText('Product catalog exported.')
            except OSError as error:
                self.status.setText('Export failed: ' + str(error))

    def choose_download(self):
        if not self._require_session():
            return
        if not self.artifacts:
            item = self.table.item(self.table.currentRow(), 0)
            if item is not None:
                self.download_product(self.products[item.data(QtCore.Qt.ItemDataRole.UserRole)])
            else:
                self.status.setText('Choose a product’s Download button to fetch its installers automatically.')
            return
        item = self.table.item(self.table.currentRow(), 0)
        product = self.products[item.data(QtCore.Qt.ItemDataRole.UserRole)] if item is not None else None
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
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, 'Save verified artifact')
        if not directory:
            return
        self.download_artifact(artifact, directory)

    def download_artifact(self, artifact, directory):
        """Shared action for the picker and the end-to-end GUI verification."""
        if not self._require_session():
            return
        from download_manager import resolve_artifact, download
        token = self._token
        def operation():
            spec = resolve_artifact(artifact, token)
            path = download(spec, directory, cancelled=self._cancel.is_set,
                            progress=lambda current, total: self._events.put(('progress', (current, total))))
            return {'path': str(path), 'sha256': spec.sha256, 'artifact': artifact}
        self._run('Resolving and downloading selected artifact…', operation, 'download', download=True)

    def inspect_package(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Inspect Linux package', '', 'Debian package (*.deb)')
        if path:
            from package_inspection import inspect_deb
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
        from arch_package import install_verified_vst
        self._run('Preparing and installing the verified native VST payload…',
                  lambda: install_verified_vst(canonical, digest), 'install')

    def closeEvent(self, event):
        self._cancel.set()
        self._token = None
        self._refresh_token = None
        if self._busy:
            self._closing = True
            self.status.setText('Stopping active operation and cleaning up…')
            event.ignore()
            return
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
