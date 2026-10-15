"""Exact original NI application profiles over the qualified private Wine lifecycle.

Profiles contain public immutable metadata only. No generic installer guessing,
NI custom-action execution, entitlement changes or binary modification occurs.
"""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable
import zipfile

from wine_manager import (WineManager, WineError, WineCancelled, InstallResult,
                          _relative, _directory, _ancestry, _regular, _digest,
                          _copy_stream, _archive_members, _place_files, _publish_directory)


@dataclass(frozen=True)
class InstallerArtifact:
    zip_size: int
    zip_sha256: str
    setup_name: str
    setup_size: int
    setup_sha256: str
    archive_file_count: int


@dataclass(frozen=True)
class BundledRuntime:
    path: str
    size: int
    sha256: str
    arguments: tuple[str, ...] = ('/install', '/quiet', '/norestart')
    accepted_exits: tuple[int, ...] = (0, 194)


@dataclass(frozen=True)
class PublicRegistryValue:
    key: str
    name: str
    value: str
    view: int = 64


@dataclass(frozen=True)
class ApplicationProfile:
    key: str
    title: str
    version: str
    upid: str
    artifact: InstallerArtifact
    plan_sha256: str
    fingerprints_sha256: str
    file_count: int
    payload_bytes: int
    executable_target: str
    allowed_target_roots: tuple[str, ...]
    load_plan: Callable
    load_hashes: Callable
    registry_values: tuple[PublicRegistryValue, ...] = ()
    runtime: BundledRuntime | None = None
    minimum_free_bytes: int = 3 * 1024**3
    initialization_timeout: int = 300


def _sha256(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def validate_payload(profile):
    """Fixed target roots, complete fingerprints and exact size/count coverage."""
    plan, hashes = profile.load_plan(), profile.load_hashes()
    if not isinstance(plan, dict) or plan.get('unresolved') or not isinstance(hashes, dict):
        raise WineError('Incomplete original application metadata')
    rows = plan.get('files')
    if not isinstance(rows, list) or len(rows) != profile.file_count:
        raise WineError('Unexpected original application file count')
    roots = tuple(_relative(root).parts for root in profile.allowed_target_roots)
    destinations = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'target', 'size'}:
            raise WineError('Unexpected original application placement schema')
        source, target = _relative(row['source']), _relative(row['target'])
        if source.parts[0] != 'OFFLINE' or not any(target.parts[:len(root)] == root for root in roots):
            raise WineError('Unrecognized original application payload root')
        if type(row['size']) is not int or row['size'] < 0:
            raise WineError('Invalid original application payload size')
        key = str(target).casefold()
        if key in destinations:
            raise WineError('Duplicate original application destination')
        destinations.add(key)
        if not _sha256(hashes.get(row['target'])):
            raise WineError('Missing original application fingerprint')
    if set(hashes) != {row['target'] for row in rows} or profile.executable_target not in hashes:
        raise WineError('Incomplete original application fingerprint coverage')
    if sum(row['size'] for row in rows) != profile.payload_bytes:
        raise WineError('Unexpected original application payload bytes')
    return rows, hashes


class NiApplicationManager(WineManager):
    def __init__(self, profile, settings, progress=None, cancelled=None):
        super().__init__(settings, progress=progress, cancelled=cancelled)
        if not isinstance(profile, ApplicationProfile) or not re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', profile.key):
            raise WineError('Unrecognized application profile')
        if not profile.allowed_target_roots or not _sha256(profile.plan_sha256) or not _sha256(profile.fingerprints_sha256):
            raise WineError('Incomplete application profile identity')
        artifact = profile.artifact
        if not _sha256(artifact.zip_sha256) or not _sha256(artifact.setup_sha256):
            raise WineError('Incomplete original installer identity')
        if len(_relative(artifact.setup_name).parts) != 1:
            raise WineError('Unexpected original installer member name')
        for value in profile.registry_values:
            if (not value.key.startswith('HKLM\\SOFTWARE\\Native Instruments\\')
                    or value.name not in ('InstallDir', 'InstallVST64Dir', 'InstallVST3Dir', 'ContentDir')
                    or any(word in value.key.casefold() for word in ('license', 'licensing', 'account', 'activation', 'serial'))
                    or any(char in value.key + value.value for char in ('\x00', '\r', '\n'))
                    or value.view not in (32, 64) or not value.value.startswith(('C:\\Program Files\\', 'C:\\Program Files (x86)\\'))):
                raise WineError('Unrecognized public installation path metadata')
        self.profile = profile
        self.prefix = self.prefix_root / profile.key
        self.receipt_name = '.native-access-linux-' + profile.key + '.json'

    def preflight(self):
        return [replace(item, message='The validated application runtime uses an AVX-capable CPU; this host is outside that qualification baseline.')
                if item.code == 'cpu' and item.status == 'error' else item for item in super().preflight()]

    def _result(self):
        profile = self.profile
        return InstallResult(profile.title, profile.version, 'installed', 'unverified', 'wine',
                             str(self.prefix), str(self.prefix/'drive_c'/profile.executable_target),
                             str(self.prefix/self.receipt_name))

    def register_installation_paths(self, prefix=None):
        target = self.prefix if prefix is None else Path(prefix)
        if target == self.prefix:
            self.verify_installation()
        elif not (target.name == 'prefix' and target.parent.parent == self.prefix_root
                  and target.parent.name.startswith('.' + self.profile.key + '-install-')):
            raise WineError('Path registration requires this managed application prefix')
        _ancestry(target)
        _directory(target)
        executable = target/'drive_c'/self.profile.executable_target
        _regular(executable)
        if _digest(executable, self.cancelled) != self.profile.load_hashes()[self.profile.executable_target]:
            raise WineError('Original application executable required for path registration')
        if not self.profile.registry_values:
            return
        self._prepare_display()
        self._emit('registering', message='Registering the original application installation paths')
        for value in self.profile.registry_values:
            self._run([self._wine(), 'reg', 'add', value.key, '/v', value.name,
                       '/t', 'REG_SZ', '/d', value.value, '/f', '/reg:' + str(value.view)], prefix=target, timeout=30)

    def install(self, installer_zip):
        profile, artifact = self.profile, self.profile.artifact
        if not self.settings.manage_wine:
            raise WineError('Managed Wine installation is disabled. Enable it in Settings.')
        errors = [item.message for item in self.preflight() if item.status == 'error']
        if errors:
            raise WineError('\n'.join(errors))
        if self.prefix.exists() or self.prefix.is_symlink():
            raise WineError(profile.title + ' prefix already exists. Existing files are preserved.')
        rows, hashes = validate_payload(profile)
        original = Path(installer_zip).absolute()
        _ancestry(original.parent)
        _regular(original, artifact.zip_size)
        self._emit('verifying', 0, artifact.zip_size, 'Checking the original ' + profile.title + ' installer')
        if _digest(original, self.cancelled) != artifact.zip_sha256:
            raise WineError('Unsupported installer. This profile accepts only the verified original ' + profile.title + ' ' + profile.version + ' ZIP.')
        self._prepare_display()
        ancestor = self.prefix_root
        while not ancestor.exists() and not ancestor.is_symlink(): ancestor = ancestor.parent
        _ancestry(ancestor)
        self.prefix_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        _ancestry(self.prefix_root)
        _directory(self.prefix_root)
        if shutil.disk_usage(self.prefix_root).free < profile.minimum_free_bytes:
            raise WineError('Insufficient free space for original application extraction and prefix staging')
        wine = self._wine()
        extractor = shutil.which('7z') or shutil.which('7zz')
        with tempfile.TemporaryDirectory(prefix='.' + profile.key + '-install-', dir=self.prefix_root) as temporary:
            staging, stage_prefix = Path(temporary), Path(temporary)/'prefix'
            try:
                snapshot = staging/'installer.zip'
                with original.open('rb') as incoming, snapshot.open('xb') as outgoing:
                    _copy_stream(incoming, outgoing, self.cancelled)
                if _digest(snapshot, self.cancelled) != artifact.zip_sha256:
                    raise WineError('Original installer changed while preparing installation')
                self._emit('extracting', message='Extracting the original ' + profile.title + ' installer')
                with zipfile.ZipFile(snapshot) as archive:
                    members = archive.infolist()
                    if (len(members) != 1 or members[0].filename != artifact.setup_name
                            or members[0].file_size != artifact.setup_size or members[0].flag_bits & 1):
                        raise WineError('Unexpected original application ZIP layout')
                    setup = staging/artifact.setup_name
                    with archive.open(members[0]) as incoming, setup.open('xb') as outgoing:
                        _copy_stream(incoming, outgoing, self.cancelled)
                if _digest(setup, self.cancelled) != artifact.setup_sha256:
                    raise WineError('Original setup executable fingerprint mismatch')
                inventory = _archive_members(self._run([extractor, 'l', '-slt', '-ba', str(setup)], timeout=120))
                files = [entry for entry in inventory if entry.get('Folder') != '+' and 'D' not in entry.get('Attributes', '')]
                if len(files) != artifact.archive_file_count:
                    raise WineError('Unexpected original installer archive inventory')
                extracted = staging/'source'
                extracted.mkdir(mode=0o700)
                self._run([extractor, 'x', '-y', '-bd', '-bb0', '-o' + str(extracted), str(setup)], timeout=600)
                for folder, directories, names in os.walk(extracted, followlinks=False):
                    for name in directories: _directory(Path(folder)/name)
                    for name in names: _regular(Path(folder)/name)
                source_root = extracted/'data'
                _directory(source_root)
                for index, row in enumerate(rows, 1):
                    path = source_root/_relative(row['source'])
                    _regular(path, row['size'])
                    if _digest(path, self.cancelled) != hashes[row['target']]:
                        raise WineError('Original application payload fingerprint mismatch: ' + row['target'])
                    if index % 100 == 0: self._emit('verifying', index, len(rows), 'Verifying original application files')
                runtime = profile.runtime
                if runtime:
                    runtime_path = extracted/_relative(runtime.path)
                    _regular(runtime_path, runtime.size)
                    if _digest(runtime_path, self.cancelled) != runtime.sha256:
                        raise WineError('Original bundled runtime fingerprint mismatch')
                self._emit('initializing', message='Preparing the private application runtime; first startup can take several minutes')
                stage_prefix.mkdir(mode=0o700)
                self._run([wine, 'wineboot.exe', '--init'], prefix=stage_prefix, timeout=profile.initialization_timeout)
                for architecture in ('system32', 'syswow64'):
                    _regular(stage_prefix/'drive_c/windows'/architecture/'kernel32.dll')
                self._run([wine, 'reg', 'add', r'HKCU\Software\Wine', '/v', 'Version', '/d', 'win10', '/f'], prefix=stage_prefix, timeout=30)
                if runtime:
                    self._emit('dependencies', message='Installing the original bundled runtime')
                    self._run([wine, str(runtime_path), *runtime.arguments], prefix=stage_prefix,
                              timeout=300, accepted=runtime.accepted_exits)
                placed = _place_files(source_root, stage_prefix/'drive_c', rows, cancelled=self.cancelled, progress=self.progress)
                if placed != hashes: raise WineError('Placed application files differ from the original fingerprints')
                self.register_installation_paths(prefix=stage_prefix)
                receipt = {'schema': 1, 'profile': profile.key, 'title': profile.title, 'version': profile.version,
                           'upid': profile.upid, 'activation': 'unverified', 'backend': 'wine',
                           'installer_sha256': artifact.zip_sha256, 'plan_sha256': profile.plan_sha256,
                           'fingerprints_sha256': profile.fingerprints_sha256, 'files': placed,
                           'method': 'verified original payload placement; MSI custom actions not reproduced',
                           'wine': self._run([wine, '--version'], timeout=15).strip(), 'bridge': 'not verified',
                           'separate_libraries': 'not installed by this application profile'}
                with (stage_prefix/self.receipt_name).open('x', encoding='utf-8') as stream: json.dump(receipt, stream)
                (stage_prefix/self.receipt_name).chmod(0o600)
                self._emit('publishing', message='Completing ' + profile.title + ' installation')
                self._stop_prefix(wine, stage_prefix, strict=True)
                if self.cancelled and self.cancelled(): raise WineCancelled('Application installation cancelled')
                _publish_directory(stage_prefix, self.prefix)
            finally:
                if stage_prefix.exists(): self._stop_prefix(wine, stage_prefix)
        # Publication succeeded. A closed UI/progress receiver or late cancel
        # cannot turn the completed installation into a reported rollback.
        try:
            self._emit('complete', 1, 1, profile.title + ' installed; NI activation remains unverified')
        except Exception:
            pass
        return self._result()

    def installation_status(self):
        profile = self.profile
        missing = {'title': profile.title, 'version': profile.version, 'status': 'not installed',
                   'installed': False, 'activation': 'unverified', 'backend': 'wine', 'managed': True}
        if not self.prefix.exists() and not self.prefix.is_symlink(): return missing
        try:
            _ancestry(self.prefix)
            _directory(self.prefix)
            path = self.prefix/self.receipt_name
            _regular(path)
            if path.stat().st_size > 4*1024*1024: raise WineError('Invalid application receipt size')
            receipt = json.loads(path.read_text(encoding='utf-8'))
            expected = {'schema': 1, 'profile': profile.key, 'title': profile.title, 'version': profile.version,
                        'upid': profile.upid, 'installer_sha256': profile.artifact.zip_sha256,
                        'plan_sha256': profile.plan_sha256, 'fingerprints_sha256': profile.fingerprints_sha256}
            if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items()):
                raise WineError('Unrecognized application installation receipt')
            rows, hashes = validate_payload(profile)
            if receipt.get('files') != hashes: raise WineError('Incomplete original application receipt fingerprints')
            checked = set()
            for row in rows:
                path = self.prefix/'drive_c'/_relative(row['target'])
                parent = path.parent
                while parent != self.prefix:
                    if parent in checked: break
                    _directory(parent)
                    checked.add(parent)
                    parent = parent.parent
                _regular(path, row['size'])
            return {**self._result().to_dict(), 'installed': True}
        except (OSError, ValueError, TypeError, WineError) as exc:
            return {**missing, 'status': 'needs repair', 'message': str(exc)}

    def verify_installation(self):
        status = self.installation_status()
        if not status['installed']: raise WineError(status.get('message', self.profile.title + ' is not installed'))
        hashes = self.profile.load_hashes()
        for index, (relative, digest) in enumerate(hashes.items(), 1):
            if _digest(self.prefix/'drive_c'/_relative(relative), self.cancelled) != digest:
                raise WineError('Installed original application file changed: ' + relative)
            if index % 100 == 0: self._emit('verifying', index, len(hashes), 'Checking installed application files')
        return self._result()

    def installed_products(self):
        status = self.installation_status()
        return [status] if status.get('installed') else []

    def launch_application(self):
        status = self.installation_status()
        if not status['installed']: raise WineError(status.get('message', self.profile.title + ' is not installed'))
        executable = self.prefix/'drive_c'/self.profile.executable_target
        if _digest(executable, self.cancelled) != self.profile.load_hashes()[self.profile.executable_target]:
            raise WineError('Original application executable changed; launch refused')
        self._prepare_display()
        return subprocess.Popen([self._wine(), str(executable)], env=self._env(self.prefix), cwd=executable.parent,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def launch_record(self, record):
        status = self.installation_status()
        if (not isinstance(record, dict) or not status.get('installed') or record.get('managed') is not True
                or any(record.get(key) != status.get(key) for key in ('title', 'version', 'backend', 'prefix', 'executable', 'receipt'))):
            raise WineError('Launch record does not match the verified managed application')
        return self.launch_application()

    def install_kontakt_890(self, *args, **kwargs):
        raise WineError('Use this exact application profile installer')

    def launch_kontakt(self):
        raise WineError('Use this exact application profile launcher')

    def detect_legacy_installation(self):
        return None
