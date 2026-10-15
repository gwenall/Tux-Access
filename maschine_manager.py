"""Exact original Maschine 2.18.4 payload installation into a private Wine prefix.

No NI binary is shipped, patched or copied from Windows. Product libraries,
controller drivers and activation are separate, unverified states.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from maschine_2184_plan import load_plan, load_hashes, PLAN_SHA256, HASHES_SHA256
from wine_manager import (WineManager, WineError, WineCancelled, InstallResult,
                          _relative, _directory, _ancestry, _regular, _digest,
                          _copy_stream, _archive_members, _place_files,
                          _publish_directory)

ZIP_SHA256 = '7ed619e713405d14b5097b40a785a5c2081b54ffd393f66b8e4628020d722798'
ZIP_SIZE = 332547451
SETUP_NAME = 'Maschine 2 2.18.4 Setup PC.exe'
SETUP_SIZE = 332925224
SETUP_SHA256 = 'acaef2e6278bc5b19eef19010d05bcbe7c988460102d6445b77dd442cfb74375'
PAYLOAD_COUNT = 793
PAYLOAD_SIZE = 454585919
EXE_TARGET = 'Program Files/Native Instruments/Maschine 2/Maschine 2.exe'
RECEIPT = '.native-access-linux-maschine.json'
VCREDIST_PATH = 'data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe'
VCREDIST_SIZE = 25234792
VCREDIST_SHA256 = 'ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4'
INSTALLATION_KEY = r'HKLM\SOFTWARE\Native Instruments\Maschine 2'
INSTALLATION_PATHS = (
    ('InstallDir', 'C:\\Program Files\\Native Instruments\\Maschine 2\\'),
    ('InstallVST64Dir', 'C:\\Program Files\\Native Instruments\\VSTPlugins 64 bit\\'),
)


def validate_maschine_plan(plan, hashes):
    if not isinstance(plan, dict) or plan.get('unresolved') or plan.get('skipped') != 0:
        raise WineError('Incomplete Maschine placement metadata')
    rows = plan.get('files')
    if not isinstance(rows, list) or len(rows) != PAYLOAD_COUNT or not isinstance(hashes, dict):
        raise WineError('Unexpected Maschine payload manifest')
    destinations = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'target', 'size'}:
            raise WineError('Unexpected Maschine placement schema')
        source, target = _relative(row['source']), _relative(row['target'])
        if source.parts[0] != 'OFFLINE' or target.parts[0] != 'Program Files':
            raise WineError('Unrecognized Maschine payload root')
        if type(row['size']) is not int or row['size'] < 0:
            raise WineError('Invalid Maschine payload size')
        key = str(target).casefold()
        if key in destinations:
            raise WineError('Duplicate Maschine payload destination')
        destinations.add(key)
        digest = hashes.get(row['target'])
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise WineError('Missing or invalid original Maschine fingerprint')
    if set(hashes) != {row['target'] for row in rows} or sum(row['size'] for row in rows) != PAYLOAD_SIZE:
        raise WineError('Unexpected Maschine manifest coverage or bytes')
    return rows


class MaschineManager(WineManager):
    def __init__(self, settings, progress=None, cancelled=None):
        super().__init__(settings, progress=progress, cancelled=cancelled)
        self.prefix = self.prefix_root / 'maschine-2'

    def preflight(self):
        diagnostics = super().preflight()
        # The common runtime was qualified on an AVX-capable host. Do not turn
        # that observation into a new technical hardware claim for Maschine.
        return [replace(item, message='The validated Maschine runtime uses an AVX-capable CPU; this host is outside that qualification baseline.')
                if item.code == 'cpu' and item.status == 'error' else item for item in diagnostics]

    def _result(self):
        return InstallResult('Maschine 2', '2.18.4', 'installed', 'unverified', 'wine',
                             str(self.prefix), str(self.prefix / 'drive_c' / EXE_TARGET),
                             str(self.prefix / RECEIPT))

    def register_installation_paths(self, prefix=None):
        """Write only the two selected original MSI public 64-bit path values.

        Supports this managed installation or its fresh private staging prefix;
        the caller must stop an existing application session before maintenance.
        No content, account, serial, entitlement or activation state is accessed.
        """
        target = self.prefix if prefix is None else Path(prefix)
        if target == self.prefix:
            self.verify_installation()
        elif not (target.name == 'prefix' and target.parent.parent == self.prefix_root
                  and target.parent.name.startswith('.maschine-install-')):
            raise WineError('Installation path registration requires the managed Maschine prefix')
        _ancestry(target)
        _directory(target)
        executable = target / 'drive_c' / EXE_TARGET
        _regular(executable)
        if _digest(executable, self.cancelled) != load_hashes()[EXE_TARGET]:
            raise WineError('Original Maschine executable required for path registration')
        self._prepare_display()
        wine = self._wine()
        self._emit('registering', message='Registering the original Maschine installation paths')
        for name, value in INSTALLATION_PATHS:
            self._run([wine, 'reg', 'add', INSTALLATION_KEY, '/v', name,
                       '/t', 'REG_SZ', '/d', value, '/f', '/reg:64'],
                      prefix=target, timeout=30)
        return dict(INSTALLATION_PATHS)

    def install_maschine_2184(self, installer_zip):
        if not self.settings.manage_wine:
            raise WineError('Managed Wine installation is disabled. Enable it in Settings.')
        errors = [item.message for item in self.preflight() if item.status == 'error']
        if errors:
            raise WineError('\n'.join(errors))
        if self.prefix.exists() or self.prefix.is_symlink():
            raise WineError('Maschine prefix already exists. Existing files are preserved; choose another Wine prefix directory in Settings.')
        hashes = load_hashes()
        rows = validate_maschine_plan(load_plan(), hashes)
        original = Path(installer_zip).absolute()
        _ancestry(original.parent)
        _regular(original, ZIP_SIZE)
        self._emit('verifying', 0, ZIP_SIZE, 'Checking the official Maschine 2.18.4 installer')
        if _digest(original, self.cancelled) != ZIP_SHA256:
            raise WineError('Unsupported Maschine installer. This adapter accepts only the verified official 2.18.4 ZIP.')
        self._emit('display', message='Preparing the Wine desktop display')
        self._prepare_display()
        ancestor = self.prefix_root
        while not ancestor.exists() and not ancestor.is_symlink():
            ancestor = ancestor.parent
        _ancestry(ancestor)
        self.prefix_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        _ancestry(self.prefix_root)
        _directory(self.prefix_root)
        if shutil.disk_usage(self.prefix_root).free < 3 * 1024**3:
            raise WineError('Maschine needs at least 3 GiB free for verified extraction and prefix staging.')
        wine = self._wine()
        extractor = shutil.which('7z') or shutil.which('7zz')
        with tempfile.TemporaryDirectory(prefix='.maschine-install-', dir=self.prefix_root) as temporary:
            staging = Path(temporary)
            stage_prefix = staging / 'prefix'
            try:
                snapshot = staging / 'installer.zip'
                with original.open('rb') as incoming, snapshot.open('xb') as outgoing:
                    _copy_stream(incoming, outgoing, self.cancelled)
                if _digest(snapshot, self.cancelled) != ZIP_SHA256:
                    raise WineError('Maschine installer changed while preparing installation')
                self._emit('extracting', message='Extracting the original Maschine installer')
                with zipfile.ZipFile(snapshot) as archive:
                    members = archive.infolist()
                    if len(members) != 1 or members[0].filename != SETUP_NAME or members[0].file_size != SETUP_SIZE or members[0].flag_bits & 1:
                        raise WineError('Unexpected Maschine ZIP layout')
                    setup = staging / SETUP_NAME
                    with archive.open(members[0]) as incoming, setup.open('xb') as outgoing:
                        _copy_stream(incoming, outgoing, self.cancelled)
                if _digest(setup, self.cancelled) != SETUP_SHA256:
                    raise WineError('Original Maschine setup executable digest mismatch')
                inventory = _archive_members(self._run([extractor, 'l', '-slt', '-ba', str(setup)], timeout=120))
                files = [entry for entry in inventory if entry.get('Folder') != '+' and 'D' not in entry.get('Attributes', '')]
                if len(files) != 819:
                    raise WineError('Unexpected original Maschine installer file count')
                extracted = staging / 'source'
                extracted.mkdir(mode=0o700)
                self._run([extractor, 'x', '-y', '-bd', '-bb0', '-o' + str(extracted), str(setup)], timeout=600)
                for folder, directories, names in os.walk(extracted, followlinks=False):
                    for name in directories:
                        _directory(Path(folder) / name)
                    for name in names:
                        _regular(Path(folder) / name)
                source_root = extracted / 'data'
                _directory(source_root)
                for index, row in enumerate(rows, 1):
                    path = source_root / _relative(row['source'])
                    _regular(path, row['size'])
                    if _digest(path, self.cancelled) != hashes[row['target']]:
                        raise WineError('Original Maschine payload fingerprint mismatch: ' + row['target'])
                    if index % 100 == 0:
                        self._emit('verifying', index, len(rows), 'Verifying original Maschine payload')
                runtime = extracted / VCREDIST_PATH
                _regular(runtime, VCREDIST_SIZE)
                if _digest(runtime, self.cancelled) != VCREDIST_SHA256:
                    raise WineError('Original bundled Maschine Visual C++ runtime digest mismatch')
                self._emit('initializing', message='Preparing the private Maschine Windows runtime; cold initialization can take several minutes')
                stage_prefix.mkdir(mode=0o700)
                self._run([wine, 'wineboot.exe', '--init'], prefix=stage_prefix, timeout=300)
                for architecture in ('system32', 'syswow64'):
                    try:
                        _regular(stage_prefix / 'drive_c/windows' / architecture / 'kernel32.dll')
                    except (OSError, WineError) as exc:
                        raise WineError('Maschine Wine initialization did not create its required ' + architecture + ' system files') from exc
                self._run([wine, 'reg', 'add', r'HKCU\Software\Wine', '/v', 'Version', '/d', 'win10', '/f'], prefix=stage_prefix, timeout=30)
                self._emit('dependencies', message='Installing the original bundled Visual C++ runtime')
                self._run([wine, str(runtime), '/install', '/quiet', '/norestart'], prefix=stage_prefix, timeout=300, accepted=(0, 194))
                placed = _place_files(source_root, stage_prefix / 'drive_c', rows,
                                      cancelled=self.cancelled, progress=self.progress)
                if placed != hashes:
                    raise WineError('Placed Maschine files differ from the verified original payload')
                self.register_installation_paths(prefix=stage_prefix)
                receipt = {'schema': 1, 'title': 'Maschine 2', 'version': '2.18.4',
                           'status': 'installed', 'activation': 'unverified', 'backend': 'wine',
                           'installer_sha256': ZIP_SHA256, 'plan_sha256': PLAN_SHA256,
                           'fingerprints_sha256': HASHES_SHA256,
                           'method': 'verified original payload placement; MSI custom actions not reproduced',
                           'wine': self._run([wine, '--version'], timeout=15).strip(),
                           'files': placed, 'bridge': 'not verified', 'factory_libraries': 'not installed by this adapter',
                           'controller_drivers': 'not installed by this adapter'}
                with (stage_prefix / RECEIPT).open('x', encoding='utf-8') as stream:
                    json.dump(receipt, stream)
                (stage_prefix / RECEIPT).chmod(0o600)
                self._emit('publishing', message='Completing Maschine installation')
                self._stop_prefix(wine, stage_prefix, strict=True)
                if self.cancelled and self.cancelled():
                    raise WineCancelled('Maschine installation cancelled')
                _publish_directory(stage_prefix, self.prefix)
            finally:
                if stage_prefix.exists():
                    self._stop_prefix(wine, stage_prefix)
        self._emit('complete', 1, 1, 'Maschine installed; NI activation remains unverified')
        return self._result()

    def installation_status(self):
        missing = {'title': 'Maschine 2', 'version': '2.18.4', 'status': 'not installed',
                   'installed': False, 'activation': 'unverified', 'backend': 'wine', 'managed': True}
        if not self.prefix.exists() and not self.prefix.is_symlink():
            return missing
        try:
            _ancestry(self.prefix)
            _directory(self.prefix)
            receipt_path = self.prefix / RECEIPT
            _regular(receipt_path)
            if receipt_path.stat().st_size > 1024 * 1024:
                raise WineError('Invalid Maschine installation receipt')
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not isinstance(receipt, dict) or receipt.get('schema') != 1 or receipt.get('version') != '2.18.4' or receipt.get('installer_sha256') != ZIP_SHA256 or receipt.get('plan_sha256') != PLAN_SHA256 or receipt.get('fingerprints_sha256') != HASHES_SHA256:
                raise WineError('Unrecognized Maschine installation receipt')
            hashes = load_hashes()
            rows = validate_maschine_plan(load_plan(), hashes)
            if receipt.get('files') != hashes:
                raise WineError('Maschine receipt does not match the complete original fingerprints')
            checked = set()
            for row in rows:
                path = self.prefix / 'drive_c' / _relative(row['target'])
                parent = path.parent
                while parent != self.prefix:
                    if parent in checked:
                        break
                    _directory(parent)
                    checked.add(parent)
                    parent = parent.parent
                _regular(path, row['size'])
            return {**self._result().to_dict(), 'installed': True}
        except (OSError, ValueError, TypeError, WineError) as exc:
            return {**missing, 'status': 'needs repair', 'message': str(exc)}

    def verify_installation(self):
        status = self.installation_status()
        if not status['installed']:
            raise WineError(status.get('message', 'Maschine is not installed'))
        hashes = load_hashes()
        for index, (relative, digest) in enumerate(hashes.items(), 1):
            if _digest(self.prefix / 'drive_c' / _relative(relative), self.cancelled) != digest:
                raise WineError('Installed Maschine file changed: ' + relative)
            if index % 100 == 0:
                self._emit('verifying', index, len(hashes), 'Checking installed Maschine files')
        return self._result()

    def launch_maschine(self):
        status = self.installation_status()
        if not status['installed']:
            raise WineError(status.get('message', 'Maschine is not installed'))
        executable = self.prefix / 'drive_c' / EXE_TARGET
        if _digest(executable, self.cancelled) != load_hashes()[EXE_TARGET]:
            raise WineError('Installed Maschine executable changed; launch refused')
        self._prepare_display()
        return subprocess.Popen([self._wine(), str(executable)], env=self._env(self.prefix),
                                cwd=executable.parent, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)

    def launch_record(self, record):
        if not isinstance(record, dict) or record.get('backend') != 'wine' or record.get('version') != '2.18.4' or record.get('managed') is not True:
            raise WineError('Unrecognized Maschine launch record')
        valid = self.installation_status()
        if not valid.get('installed') or any(record.get(key) != valid.get(key) for key in ('title', 'prefix', 'executable', 'receipt')):
            raise WineError('Maschine launch record does not match its verified managed installation')
        return self.launch_maschine()
