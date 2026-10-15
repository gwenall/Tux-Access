"""User-owned Wine lifecycle for the exact, verified Kontakt 8.9.0 artifact.

No NI payload, account state or activation data is distributed or imported.
Installation means original payload verified and placed, never activation.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import zipfile

from tux_access.installation.plans.kontakt_890 import load_plan, PLAN_SHA256
from tux_access.installation.wine.display import ensure_display, DisplayError

ZIP_SHA256 = '3c711e00494a369cce1604d9640598999612f08af422a5f39c9bd9163e29728d'
ZIP_SIZE = 1166054646
SETUP_NAME = 'Kontakt 8 8.9.0 Setup PC.exe'
SETUP_SIZE = 1166054456
PAYLOAD_COUNT = 8134
PAYLOAD_SIZE = 1940318107
EXE_TARGET = 'Program Files/Native Instruments/Kontakt 8/Kontakt 8.exe'
VST3_TARGET = 'Program Files/Common Files/VST3/Kontakt 8.vst3'
RECEIPT = '.native-access-linux-kontakt.json'
LEGACY_RECEIPT_SHA256 = '799f6a7d65b0ef460ddf4d74d02fef2cbf5c7883c31ae1e7a04c1d86be79700d'
EXE_SHA256 = '3f7b47a263254d01b609db0f2ea606352ea1c1dfda42de2050a4ff58a875751e'
VST3_SHA256 = 'b00c4da89d56602ad54aff11ce8591bc3aacdb29c6e620328dea731cb61321c9'
# Filled from the official, digest-verified installer inventory, not a download.
VCREDIST_PATH = 'data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe'
VCREDIST_SIZE = 25640112
VCREDIST_SHA256 = '1821577409c35b2b9505ac833e246376cc68a8262972100444010b57226f0940'


class WineError(RuntimeError):
    pass


class WineCancelled(WineError):
    pass


@dataclass(frozen=True)
class Diagnostic:
    code: str
    status: str
    message: str
    action: str = ''


@dataclass(frozen=True)
class InstallResult:
    title: str
    version: str
    status: str
    activation: str
    backend: str
    prefix: str
    executable: str
    receipt: str
    managed: bool = True
    source: str = 'managed installation'

    def to_dict(self):
        return asdict(self)


def _relative(value):
    if not isinstance(value, str) or not value or any(c in value for c in ('\\', ':', '\x00', '\n', '\r')):
        raise WineError('Unsafe payload path')
    parts = value.split('/')
    if value.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise WineError('Unsafe payload path')
    return PurePosixPath(value)


def _directory(path, *, owned=True):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (owned and hasattr(os, 'getuid') and info.st_uid != os.getuid()):
        raise WineError(f'Unsafe or foreign-owned directory: {path}')


def _ancestry(path, *, owned=False):
    for parent in reversed((path, *path.parents)):
        _directory(parent, owned=owned)


def _regular(path, size=None):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (size is not None and info.st_size != size):
        raise WineError(f'Unexpected file type or size: {path.name}')
    return info


def _digest(path, cancelled=None):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            if cancelled and cancelled():
                raise WineCancelled('Installation cancelled')
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return value.hexdigest()
            value.update(chunk)


def _try_clone(incoming, outgoing):
    """Copy-on-write optimization only; ordinary streaming remains the fallback."""
    if platform.system() == 'Linux':
        try:
            import fcntl
            info = os.fstat(incoming.fileno())
            if stat.S_ISREG(info.st_mode) and info.st_size >= 64 * 1024 and incoming.tell() == outgoing.tell() == 0:
                fcntl.ioctl(outgoing.fileno(), 0x40049409, incoming.fileno())
                return True
        except (OSError, ValueError, AttributeError):
            pass
    return False


def _copy_stream(incoming, outgoing, cancelled=None):
    if cancelled and cancelled():
        raise WineCancelled('Installation cancelled')
    # ZipExtFile has no file descriptor, so compressed extraction stays streamed.
    if _try_clone(incoming, outgoing):
        return
    while True:
        if cancelled and cancelled():
            raise WineCancelled('Installation cancelled')
        chunk = incoming.read(1024 * 1024)
        if not chunk:
            break
        outgoing.write(chunk)


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('unresolved') or plan.get('skipped') != 0:
        raise WineError('Incomplete Kontakt placement metadata')
    rows = plan.get('files', [])
    if len(rows) != PAYLOAD_COUNT:
        raise WineError('Unexpected Kontakt payload count')
    destinations = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'target', 'size'}:
            raise WineError('Unexpected placement schema')
        source, target = _relative(row['source']), _relative(row['target'])
        if source.parts[0] != 'OFFLINE' or target.parts[0] not in ('Program Files', 'ProgramData'):
            raise WineError('Unrecognized payload root')
        if type(row['size']) is not int or row['size'] < 0:
            raise WineError('Invalid payload size')
        key = str(target).casefold()
        if key in destinations:
            raise WineError('Duplicate payload destination')
        destinations.add(key)
    if sum(row['size'] for row in rows) != PAYLOAD_SIZE:
        raise WineError('Unexpected Kontakt payload bytes')
    return rows


def _place_files(source_root, target_root, rows, *, cancelled=None, progress=None):
    """No overwrite and no symlink traversal; rollback only files we create."""
    _ancestry(source_root)
    _ancestry(target_root)
    _directory(source_root)
    _directory(target_root)
    checked = set()
    records = []
    for row in rows:
        src, dst = _relative(row['source']), _relative(row['target'])
        for parent in (source_root / src).parents:
            if parent == source_root:
                break
            if parent not in checked:
                _directory(parent)
                checked.add(parent)
        source, target = source_root / src, target_root / dst
        _regular(source, row['size'])
        if target.exists() or target.is_symlink():
            raise WineError('Payload target already exists; refusing overwrite')
        records.append((source, target, row))
    created, directories, hashes = [], [], {}
    try:
        for index, (source, target, row) in enumerate(records, 1):
            if cancelled and cancelled():
                raise WineCancelled('Installation cancelled')
            parent = target_root
            for part in _relative(row['target']).parts[:-1]:
                parent /= part
                if not parent.exists() and not parent.is_symlink():
                    parent.mkdir(mode=0o700)
                    directories.append(parent)
                _directory(parent)
            digest = hashlib.sha256()
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                created.append(target)
                cloned = _try_clone(incoming, outgoing)
                while True:
                    if cancelled and cancelled():
                        raise WineCancelled('Installation cancelled')
                    chunk = incoming.read(1024 * 1024)
                    if not chunk:
                        break
                    if not cloned:
                        outgoing.write(chunk)
                    digest.update(chunk)
            target.chmod(0o644)
            if _digest(target, cancelled) != digest.hexdigest():
                raise WineError('Placed Kontakt payload checksum mismatch')
            hashes[row['target']] = digest.hexdigest()
            if progress and (index % 100 == 0 or index == len(records)):
                progress('placing', index, len(records), 'Verifying original product files')
        return hashes
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        for directory in reversed(directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _archive_members(output):
    """Validate native 7-Zip -slt output before it writes archive members."""
    members, current = [], {}
    for line in output.splitlines() + ['']:
        if not line.strip():
            if current.get('Path'):
                members.append(current)
            current = {}
        elif ' = ' in line:
            key, value = line.split(' = ', 1)
            current[key] = value
    seen = set()
    for entry in members:
        path = entry['Path'].replace('\\', '/')
        key = str(_relative(path)).casefold()
        if key in seen:
            raise WineError('Duplicate installer member')
        seen.add(key)
        if any(k in entry for k in ('Symbolic Link', 'Hard Link')) or 'L' in entry.get('Attributes', ''):
            raise WineError('Installer contains linked files')
        if entry.get('Encrypted', '-') != '-':
            raise WineError('Encrypted installer payload is unsupported')
        if not entry.get('Size', '0').isdigit():
            raise WineError('Invalid installer member size')
    if not members or len(members) > 12000 or sum(int(e.get('Size', 0)) for e in members) > 3 * 1024**3:
        raise WineError('Unexpected installer archive inventory')
    return members


class WineManager:
    def __init__(self, settings, progress=None, cancelled=None):
        self.settings = settings
        self.progress = progress
        self.cancelled = cancelled
        base = Path(settings.wine_prefix_directory).expanduser()
        if not base.is_absolute() or '..' in base.parts:
            raise WineError('Wine prefix directory must be an absolute path')
        self.prefix_root = base
        self.prefix = base / 'kontakt-8'
        self._display_overrides = {}
        self._last_initialization_log = None

    def _emit(self, stage, completed=0, total=0, message=''):
        if stage != 'complete' and self.cancelled and self.cancelled():
            raise WineCancelled('Installation cancelled')
        if self.progress:
            self.progress(stage, completed, total, message)

    def _wine(self):
        requested = self.settings.wine_executable
        found = shutil.which(requested)
        if not found:
            raise WineError('Wine is missing. Install the Arch wine package or choose a Wine executable in Settings.')
        return str(Path(found).absolute())

    def _env(self, prefix, *, initializing=False):
        env = {key: value for key, value in os.environ.items() if not key.startswith('WINE')}
        # Wine 11.19's new WoW64 runtime was validated with this exact setting;
        # win64 alone failed to initialize the original 32-bit prerequisite path.
        env.update(WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEARCH='wow64',
                   WINEDLLOVERRIDES='winemenubuilder.exe=d')
        if initializing:
            # This native C++ prefix does not need optional Mono/Gecko bootstrap
            # downloads. Suppress their first-boot prompts only during wineboot;
            # NI application launches keep normal CLR/HTML loading behavior.
            env['WINEDLLOVERRIDES'] += ';mscoree,mshtml='
        env.update(self._display_overrides)
        if self._display_overrides and not os.environ.get('DISPLAY'):
            env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        return env

    def _prepare_display(self):
        try:
            self._display_overrides = ensure_display(cancelled=self.cancelled)
        except DisplayError as exc:
            if self.cancelled and self.cancelled():
                raise WineCancelled('Installation cancelled') from exc
            raise WineError(str(exc)) from exc

    def _run(self, argv, *, prefix=None, timeout=300, accepted=(0,)):
        """No shell; bounded private output and cooperative cancellation."""
        with tempfile.TemporaryFile() as output:
            initializing = len(argv) > 1 and argv[1] in ('wineboot', 'wineboot.exe')
            process = subprocess.Popen(argv, env=self._env(prefix, initializing=initializing) if prefix else None,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=(os.name == 'posix'))
            started = time.monotonic()
            deadline = started + timeout
            next_progress = started + 10
            failure = None
            try:
                while process.poll() is None:
                    if self.cancelled and self.cancelled():
                        raise WineCancelled('Installation cancelled')
                    now = time.monotonic()
                    if now > deadline:
                        raise WineError(f'{Path(argv[0]).name} timed out. Check Runtime diagnostics.')
                    if initializing and now >= next_progress:
                        self._emit('initializing', 0, 0, f'Preparing Wine ({int(now - started)} s elapsed); first startup can take several minutes')
                        next_progress = now + 10
                    time.sleep(0.1)
                output.seek(0)
                data = output.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise WineError('Runtime output exceeded diagnostic limit')
                if process.returncode not in accepted:
                    raise WineError(f'{Path(argv[0]).name} failed (exit {process.returncode}). Check Runtime diagnostics.')
                return data.decode('utf-8', 'replace')
            except (WineError, OSError) as exc:
                failure = exc
                raise
            finally:
                if process.poll() is None:
                    if os.name == 'posix':
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        if os.name == 'posix':
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        else:
                            process.kill()
                        process.wait()
                # Only fresh prefix initialization has retained diagnostics.
                # Account/login/NI application output is never persisted here.
                if failure is not None and not isinstance(failure, WineCancelled) and prefix is not None and len(argv) > 1 and argv[1] in ('wineboot', 'wineboot.exe'):
                    try:
                        private = self.prefix_root / '.diagnostics'
                        private.mkdir(mode=0o700, exist_ok=True)
                        _ancestry(private)
                        _directory(private)
                        if private.stat().st_mode & 0o077:
                            raise WineError('Initialization diagnostics directory is not private')
                        fd, name = tempfile.mkstemp(prefix='wineboot-', suffix='.log', dir=private)
                        output.seek(0)
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write((str(failure) + '\n').encode('utf-8', 'replace'))
                            stream.write(output.read(64 * 1024))
                        self._last_initialization_log = name
                    except (OSError, WineError):
                        pass

    def preflight(self):
        results = []
        if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
            results.append(Diagnostic('platform', 'error', 'Kontakt managed installation requires x86-64 Linux.'))
        try:
            wine = self._wine()
            if not (Path(wine).parent / 'wineserver').is_file():
                raise WineError('The selected Wine executable needs its matching wineserver in the same directory.')
            version = self._run([wine, '--version'], timeout=15).strip()
            match = re.search(r'wine-(\d+)\.(\d+)', version)
            if not match or tuple(map(int, match.groups())) < (11, 19):
                results.append(Diagnostic('wine', 'error', f'{version or "Unknown Wine version"}; this prototype requires Wine 11.19 or later.', 'Install the Arch wine package or select a compatible Wine executable.'))
            else:
                results.append(Diagnostic('wine', 'ok', version + (' (validated baseline)' if match.groups() == ('11', '19') else ' (version not qualified by the prototype)')))
        except (WineError, OSError) as exc:
            results.append(Diagnostic('wine', 'error', str(exc)))
        extractor = shutil.which('7z') or shutil.which('7zz')
        if not extractor:
            results.append(Diagnostic('extractor', 'error', 'Native 7-Zip is missing.', 'Install the Arch 7zip package; the validated extractor baseline is 26.04.'))
        else:
            try:
                banner = self._run([extractor, 'i'], timeout=15)
                match = re.search(r'7-Zip(?: \(z\))? (\d+)\.(\d+)', banner)
                if not match or tuple(map(int, match.groups())) < (26, 4):
                    results.append(Diagnostic('extractor', 'error', 'The validated extractor baseline is native 7-Zip 26.04; this older or unrecognized extractor is unqualified for the prototype.', 'Select the validated Arch 7zip package.'))
                else:
                    results.append(Diagnostic('extractor', 'ok', 'Native 7-Zip ' + '.'.join(match.groups()) + (' (validated baseline)' if match.groups() == ('26', '04') else ' (version not qualified by the prototype)')))
            except (WineError, OSError) as exc:
                results.append(Diagnostic('extractor', 'error', str(exc)))
        try:
            flags = Path('/proc/cpuinfo').read_text()
            if not re.search(r'\bavx\b', flags):
                results.append(Diagnostic('cpu', 'error', 'Kontakt requires AVX. This Linux session does not advertise it.'))
        except OSError:
            results.append(Diagnostic('cpu', 'warning', 'CPU AVX support could not be checked.'))
        if os.environ.get('DISPLAY'):
            results.append(Diagnostic('display', 'ok', 'Using the current X11 desktop display.'))
        elif os.environ.get('WAYLAND_DISPLAY'):
            if shutil.which('Xwayland'):
                results.append(Diagnostic('display', 'ok', 'Wine will prepare a private authenticated Xwayland display.'))
            else:
                results.append(Diagnostic('xwayland', 'error', 'Xwayland is required for Wine on this Wayland desktop.', 'Install the Arch xorg-xwayland package.'))
        else:
            results.append(Diagnostic('display', 'error', 'Wine needs a graphical Linux session.', 'Open Tux Access from your desktop.'))
        results.extend(self._bridge_diagnostics())
        return results

    def _bridge_diagnostics(self):
        directory = self.settings.yabridge_directory
        if directory is None:
            return [Diagnostic('yabridge', 'info', 'Standalone is available without yabridge. VST3 bridging is not configured.', 'Choose a trusted yabridge directory in Settings for DAW use.')]
        directory = Path(directory).expanduser()
        if not directory.is_absolute():
            return [Diagnostic('yabridge', 'warning', 'Select an absolute yabridge directory in Settings.')]
        required = ('yabridgectl', 'yabridge-host.exe', 'libyabridge-vst3.so')
        missing = [name for name in required if not (directory / name).is_file()]
        if missing:
            return [Diagnostic('yabridge', 'warning', 'Selected yabridge directory is incomplete: ' + ', '.join(missing))]
        try:
            version = self._run([str(directory / 'yabridgectl'), '--version'], timeout=15).strip()
            return [Diagnostic('yabridge', 'info', f'{version}; selected host: {directory / "yabridge-host.exe"}. VST3 compatibility must be tested; version selection alone does not establish a successful scan.')]
        except (WineError, OSError) as exc:
            return [Diagnostic('yabridge', 'warning', str(exc))]

    def diagnose(self):
        return {'diagnostics': [asdict(item) for item in self.preflight()],
                'installation': self.installation_status(), 'prefix': str(self.prefix),
                'activation': 'unverified', 'managed': bool(self.settings.manage_wine),
                'initialization_log': self._last_initialization_log}

    def install_kontakt_890(self, installer_zip, metadata_path=None):
        if not self.settings.manage_wine:
            raise WineError('Managed Wine installation is disabled. Enable it in Settings.')
        errors = [item.message for item in self.preflight() if item.status == 'error']
        if errors:
            raise WineError('\n'.join(errors))
        if self.prefix.exists() or self.prefix.is_symlink():
            raise WineError('Kontakt prefix already exists. Existing installations are preserved; choose a new prefix directory in Settings.')
        plan = load_plan()
        if metadata_path is not None:
            raw = Path(metadata_path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != PLAN_SHA256:
                raise WineError('Unrecognized Kontakt placement metadata')
            plan = json.loads(raw)
        rows = validate_plan(plan)
        original = Path(installer_zip).absolute()
        _ancestry(original.parent)
        _regular(original, ZIP_SIZE)
        self._emit('verifying', 0, ZIP_SIZE, 'Checking the official Kontakt 8.9.0 installer')
        if _digest(original, self.cancelled) != ZIP_SHA256:
            raise WineError('Unsupported installer. Only the verified official Kontakt 8.9.0 ZIP is supported.')
        self._emit('display', message='Preparing the Wine desktop display')
        self._prepare_display()
        # Refuse symlink ancestry before creating any managed directory.
        ancestor = self.prefix_root
        while not ancestor.exists() and not ancestor.is_symlink():
            ancestor = ancestor.parent
        _ancestry(ancestor)
        self.prefix_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ancestry(self.prefix_root)
        _directory(self.prefix_root)
        if shutil.disk_usage(self.prefix_root).free < 7 * 1024**3:
            raise WineError('Kontakt installation needs at least 7 GiB free for verified extraction and staging.')
        wine = self._wine()
        extractor = shutil.which('7z') or shutil.which('7zz')
        with tempfile.TemporaryDirectory(prefix='.kontakt-install-', dir=self.prefix_root) as temporary:
            staging = Path(temporary)
            stage_prefix = staging / 'prefix'
            try:
                # Snapshot protects later operations from a changed caller-owned file.
                snapshot = staging / 'installer.zip'
                with original.open('rb') as incoming, snapshot.open('xb') as outgoing:
                    _copy_stream(incoming, outgoing, self.cancelled)
                if _digest(snapshot, self.cancelled) != ZIP_SHA256:
                    raise WineError('Installer changed while preparing installation')
                self._emit('extracting', message='Extracting the unchanged official installer')
                with zipfile.ZipFile(snapshot) as archive:
                    members = archive.infolist()
                    if len(members) != 1 or members[0].filename != SETUP_NAME or members[0].file_size != SETUP_SIZE or members[0].flag_bits & 1:
                        raise WineError('Unexpected Kontakt installer ZIP layout')
                    setup = staging / SETUP_NAME
                    with archive.open(members[0]) as incoming, setup.open('xb') as outgoing:
                        _copy_stream(incoming, outgoing, self.cancelled)
                inventory = _archive_members(self._run([extractor, 'l', '-slt', '-ba', str(setup)], timeout=120))
                archive_files = [entry for entry in inventory if entry.get('Folder') != '+' and 'D' not in entry.get('Attributes', '')]
                if len(archive_files) != 8148:
                    raise WineError('Unexpected Kontakt installer file count')
                extracted = staging / 'source'
                extracted.mkdir(mode=0o700)
                self._run([extractor, 'x', '-y', '-bd', '-bb0', '-o' + str(extracted), str(setup)], timeout=600)
                # Reject every extracted linked member even when not selected by plan.
                for root, directories, files in os.walk(extracted, followlinks=False):
                    for name in directories:
                        _directory(Path(root) / name)
                    for name in files:
                        _regular(Path(root) / name)
                source_root = extracted / 'data'
                _directory(source_root)
                runtime = extracted / VCREDIST_PATH
                _regular(runtime, VCREDIST_SIZE)
                if _digest(runtime, self.cancelled) != VCREDIST_SHA256:
                    raise WineError('The verified bundled Visual C++ runtime is missing or unsupported.')
                self._emit('initializing', message='Preparing a private Wine prefix')
                stage_prefix.mkdir(mode=0o700)
                self._run([wine, 'wineboot.exe', '--init'], prefix=stage_prefix, timeout=120)
                for architecture in ('system32', 'syswow64'):
                    try:
                        _regular(stage_prefix / 'drive_c/windows' / architecture / 'kernel32.dll')
                    except OSError as exc:
                        raise WineError('Wine prefix initialization did not create its required ' + architecture + ' system files') from exc
                self._run([wine, 'reg', 'add', r'HKCU\Software\Wine', '/v', 'Version', '/d', 'win10', '/f'], prefix=stage_prefix, timeout=30)
                self._emit('dependencies', message='Installing the original bundled Visual C++ runtime')
                self._run([wine, str(runtime), '/install', '/quiet', '/norestart'], prefix=stage_prefix, timeout=300, accepted=(0, 194))
                hashes = _place_files(source_root, stage_prefix / 'drive_c', rows,
                                      cancelled=self.cancelled, progress=self.progress)
                if hashes.get(EXE_TARGET) != EXE_SHA256 or hashes.get(VST3_TARGET) != VST3_SHA256:
                    raise WineError('Extracted Kontakt primary binaries do not match the verified original installer')
                receipt = {'schema': 1, 'title': 'Kontakt 8', 'version': '8.9.0',
                           'status': 'installed', 'backend': 'wine', 'activation': 'unverified',
                           'installer_sha256': ZIP_SHA256, 'plan_sha256': PLAN_SHA256,
                           'method': 'verified original payload placement; MSI custom actions not reproduced',
                           'wine': self._run([wine, '--version'], timeout=15).strip(),
                           'files': hashes, 'bridge': 'not verified'}
                with (stage_prefix / RECEIPT).open('x', encoding='utf-8') as stream:
                    json.dump(receipt, stream)
                (stage_prefix / RECEIPT).chmod(0o600)
                self._emit('publishing', message='Completing Kontakt installation')
                self._stop_prefix(wine, stage_prefix, strict=True)
                if self.cancelled and self.cancelled():
                    raise WineCancelled('Installation cancelled')
                # Linux exclusive publication protects concurrent installs and manual prefixes.
                _publish_directory(stage_prefix, self.prefix)
            finally:
                if stage_prefix.exists():
                    self._stop_prefix(wine, stage_prefix)
        self._emit('complete', 1, 1, 'Kontakt installed; NI activation remains unverified')
        return self._result()

    def _stop_prefix(self, wine, prefix, strict=False):
        server = Path(wine).parent / 'wineserver'
        if server.is_file():
            try:
                for option in ('-k', '-w'):
                    result = subprocess.run([str(server), option], env=self._env(prefix), timeout=15,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    # Wine returns 1 for -k when the prefix server already exited.
                    # The bounded -w success establishes shutdown in both cases.
                    if strict and option == '-w' and result.returncode:
                        raise WineError('Cannot stop the staged Wine session safely before publication')
            except (OSError, subprocess.TimeoutExpired) as exc:
                if strict:
                    raise WineError('Cannot stop the staged Wine session safely before publication') from exc
        elif strict:
            raise WineError('The selected Wine runtime has no matching wineserver')

    def _result(self):
        return InstallResult('Kontakt 8', '8.9.0', 'installed', 'unverified', 'wine',
                             str(self.prefix), str(self.prefix / 'drive_c' / EXE_TARGET), str(self.prefix / RECEIPT))

    def installation_status(self):
        if not self.prefix.exists() and not self.prefix.is_symlink():
            return {'title': 'Kontakt 8', 'version': '8.9.0', 'status': 'not installed', 'installed': False, 'activation': 'unverified', 'backend': 'wine'}
        try:
            _ancestry(self.prefix)
            _directory(self.prefix)
            receipt_path = self.prefix / RECEIPT
            _regular(receipt_path)
            if receipt_path.stat().st_size > 4 * 1024 * 1024:
                raise WineError('Invalid installation receipt')
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not isinstance(receipt, dict) or receipt.get('schema') != 1 or receipt.get('installer_sha256') != ZIP_SHA256 or receipt.get('plan_sha256') != PLAN_SHA256:
                raise WineError('Unrecognized installation receipt')
            expected = validate_plan(load_plan())
            hashes = receipt.get('files', {})
            if not isinstance(hashes, dict) or set(hashes) != {row['target'] for row in expected}:
                raise WineError('Incomplete installation receipt')
            if hashes.get(EXE_TARGET) != EXE_SHA256 or hashes.get(VST3_TARGET) != VST3_SHA256:
                raise WineError('Installation receipt does not match the verified Kontakt binaries')
            # UI detection checks presence and size. Full digest check is explicit.
            checked = set()
            for row in expected:
                path = self.prefix / 'drive_c' / _relative(row['target'])
                parent = path.parent
                while parent != self.prefix:
                    if parent in checked:
                        break
                    _directory(parent)
                    checked.add(parent)
                    parent = parent.parent
                _regular(path, row['size'])
                if not isinstance(hashes[row['target']], str) or not re.fullmatch('[0-9a-f]{64}', hashes[row['target']]):
                    raise WineError('Invalid installation receipt hashes')
            return {**self._result().to_dict(), 'installed': True}
        except (OSError, ValueError, TypeError, WineError) as exc:
            return {'title': 'Kontakt 8', 'version': '8.9.0', 'status': 'needs repair', 'installed': False, 'activation': 'unverified', 'backend': 'wine', 'message': str(exc)}

    def installed_products(self):
        item = self.installation_status()
        return [item] if item['status'] == 'installed' else []

    def detect_legacy_installation(self):
        """Read-only recognition of the one previously verified Linux experiment.

        Arbitrary record paths or imported prefixes are never accepted here.
        Activation/license/account files are not imported or inspected.
        """
        installation = Path(self.settings.installation_directory).expanduser()
        if not installation.is_absolute() or '..' in installation.parts:
            raise WineError('Installation directory must be an absolute path')
        prefix = installation / 'wine-kontakt-8-wow64'
        receipt_path = Path.home() / '.cache/native-access-linux/kontakt-installer/payload-placement-receipt.json'
        if not prefix.exists() and not prefix.is_symlink():
            return None
        incomplete = {'title': 'Kontakt 8', 'version': '8.9.0', 'status': 'needs repair',
                      'installed': False, 'activation': 'unverified', 'backend': 'wine',
                      'managed': False, 'source': 'verified legacy experiment', 'prefix': str(prefix)}
        try:
            _ancestry(prefix)
            _directory(prefix)
            _ancestry(receipt_path.parent)
            _directory(receipt_path.parent)
            _regular(receipt_path)
            if receipt_path.stat().st_size > 4 * 1024 * 1024 or not LEGACY_RECEIPT_SHA256:
                raise WineError('The known legacy installation receipt is unavailable or unqualified')
            raw = receipt_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != LEGACY_RECEIPT_SHA256:
                raise WineError('The known legacy installation receipt changed')
            receipt = json.loads(raw)
            if not isinstance(receipt, dict) or receipt.get('installer_sha256') != ZIP_SHA256 or receipt.get('version') != '8.9.0':
                raise WineError('Unrecognized legacy installation receipt')
            expected = validate_plan(load_plan())
            hashes = receipt.get('files')
            if not isinstance(hashes, dict) or set(hashes) != {row['target'] for row in expected}:
                raise WineError('Incomplete legacy installation receipt')
            checked = set()
            for index, row in enumerate(expected, 1):
                relative = _relative(row['target'])
                path = prefix / 'drive_c' / relative
                parent = path.parent
                while parent != prefix:
                    if parent in checked:
                        break
                    _directory(parent)
                    checked.add(parent)
                    parent = parent.parent
                _regular(path, row['size'])
                digest = hashes[row['target']]
                if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                    raise WineError('Invalid legacy installation hash manifest')
                if _digest(path, self.cancelled) != digest:
                    raise WineError('Known legacy Kontakt file changed: ' + row['target'])
                if index % 100 == 0:
                    self._emit('detecting', index, len(expected), 'Checking the existing Kontakt installation')
            return {'title': 'Kontakt 8', 'version': '8.9.0', 'status': 'installed',
                    'installed': True, 'activation': 'unverified', 'backend': 'wine',
                    'managed': False, 'source': 'verified legacy experiment', 'prefix': str(prefix),
                    'executable': str(prefix / 'drive_c' / EXE_TARGET), 'receipt': str(receipt_path)}
        except WineCancelled:
            raise
        except (OSError, ValueError, TypeError, WineError) as exc:
            return {**incomplete, 'message': str(exc)}

    def verify_installation(self):
        item = self.installation_status()
        if item['status'] != 'installed':
            raise WineError(item.get('message', 'Kontakt is not installed'))
        receipt = json.loads((self.prefix / RECEIPT).read_text(encoding='utf-8'))
        for index, (relative, digest) in enumerate(receipt['files'].items(), 1):
            if _digest(self.prefix / 'drive_c' / _relative(relative), self.cancelled) != digest:
                raise WineError('Installed Kontakt file changed: ' + relative)
            if index % 100 == 0:
                self._emit('verifying', index, PAYLOAD_COUNT, 'Checking installed Kontakt files')
        return self._result()

    def launch_kontakt(self):
        item = self.installation_status()
        if item['status'] != 'installed':
            raise WineError(item.get('message', 'Kontakt is not installed by Tux Access'))
        executable = self.prefix / 'drive_c' / EXE_TARGET
        self._prepare_display()
        return subprocess.Popen([self._wine(), str(executable)], env=self._env(self.prefix),
                                cwd=executable.parent, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)

    def launch_record(self, record):
        """Launch only a record revalidated against our fixed known locations."""
        if not isinstance(record, dict) or record.get('backend') != 'wine' or record.get('version') != '8.9.0':
            raise WineError('Unrecognized Kontakt launch record')
        if record.get('managed') is not False:
            valid = self.installation_status()
        else:
            valid = self.detect_legacy_installation()
        if not valid or not valid.get('installed') or any(record.get(key) != valid.get(key) for key in ('title', 'prefix', 'executable', 'receipt')):
            raise WineError('Kontakt launch record does not match a verified known installation')
        self._prepare_display()
        prefix, executable = Path(valid['prefix']), Path(valid['executable'])
        return subprocess.Popen([self._wine(), str(executable)], env=self._env(prefix),
                                cwd=executable.parent, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)


def _publish_directory(source, destination):
    """Linux renameat2 NOREPLACE; ordinary rename can replace an empty prefix."""
    if platform.system() != 'Linux':
        raise WineError('Managed prefix publication requires Linux')
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise WineError('This Linux runtime lacks safe exclusive prefix publication')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise WineError('Kontakt prefix already exists; preserving the existing directory')
        raise WineError('Cannot publish the managed Wine prefix: ' + os.strerror(code))
