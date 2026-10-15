"""One user action resolves, verifies and installs a supported NI product."""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from importlib.resources import files
import signal
import tempfile
import time

from tux_access.settings import validate_settings
from tux_access.downloads.catalog import available_artifacts
from tux_access.downloads.manager import download, resolve_artifact, DownloadCancelled
from tux_access.catalog.products import product_values


class InstallError(RuntimeError):
    pass


def _title(product):
    return ''.join(c for c in product_values(product)[0].casefold() if c.isalnum())


def can_install(product, settings):
    from tux_access.installation.backends import wine_spec
    key = _title(product)
    return (key in ('phasis', 'reaktor6', 'reaktor6fx') or
            (settings.manage_wine and wine_spec(product) is not None))


def _matches(artifact, product):
    if product.get('upid') and str(product['upid']) == artifact.upid:
        return True
    return ''.join(c for c in artifact.title.casefold() if c.isalnum()) == _title(product)


def select_artifact(product, artifacts, settings):
    if not can_install(product, settings):
        raise InstallError('Managed installation is not available for this product yet. Advanced tools can download its original installer.')
    matches = [a for a in artifacts if _matches(a, product) and a.file_type == 'installer']
    key = _title(product)
    if key in ('phasis', 'reaktor6', 'reaktor6fx'):
        matches = [a for a in matches if a.platform.startswith('linux') and a.target_file.lower().endswith('.deb')]
        backend = 'native'
    else:
        from tux_access.installation.backends import wine_spec
        spec = wine_spec(product)
        matches = [a for a in matches if a.platform.casefold().startswith(('pc', 'win')) and a.version == spec.version
                   and a.target_file == spec.filename and a.filesize == spec.size]
        backend = 'wine'
    if not matches:
        raise InstallError('Your account catalog has no installer matching the currently verified Linux workflow for this product.')
    def version(a):
        return tuple(int(n) for n in re.findall(r'\d+', a.version))
    return max(matches, key=version), backend


def installed_catalog(settings):
    from tux_access.installation.native.arch import installed_products
    result = installed_products()
    from tux_access.installation.wine.kontakt import WineManager
    manager = WineManager(settings)
    status = manager.installation_status()
    if not status.get('installed'):
        legacy = manager.detect_legacy_installation()
        if legacy and (legacy.get('installed') or status['status'] == 'not installed'):
            status = legacy
    if status['status'] != 'not installed':
        status['status'] = ('Installed · activation unverified' if status.get('installed')
                            else 'Installation needs repair')
        status['type'] = 'Application · Wine'
        status['binaryPath'] = status.get('executable', '')
        result.append(status)
    from tux_access.installation.wine.maschine import MaschineManager
    maschine = MaschineManager(settings).installation_status()
    if maschine['status'] != 'not installed':
        result.append({**maschine, 'status': ('Installed · activation unverified' if maschine.get('installed')
                                            else 'Installation needs repair'),
                       'type': 'Application · Wine', 'binaryPath': maschine.get('executable', '')})
    from tux_access.installation.wine.massive import MassiveManager
    massive = MassiveManager(settings).installation_status()
    if massive['status'] != 'not installed':
        result.append({**massive, 'status': ('Installed · activation unverified' if massive.get('installed')
                                           else 'Installation needs repair'),
                       'type': 'Application · Wine', 'binaryPath': massive.get('executable', '')})
    return result


def _check(cancelled):
    if cancelled and cancelled():
        raise DownloadCancelled('Installation cancelled')


def _cached_download(path, spec, progress, cancelled):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != spec.size:
        raise InstallError('A different file already uses the installer filename. Move it aside or choose another download folder; it will not be overwritten.')
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        current = 0
        while True:
            _check(cancelled)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            current += len(chunk)
            if current > spec.size:
                raise InstallError('The cached installer changed during verification.')
            digest.update(chunk)
            progress('verify', current, spec.size, 'Checking the existing installer against NI’s checksum')
    if current != spec.size or digest.hexdigest() != spec.sha256:
        raise InstallError('The existing installer does not match NI’s checksum. It has been preserved; choose another download folder or remove it manually.')


def _prepare_native(progress, cancelled):
    from tux_access.installation.native.arch import COMPAT_LIBRARIES
    compatibility = Path.home() / '.local/lib/native-access-linux/compat-legacy/lib'
    if all((compatibility / name).is_file() for name in COMPAT_LIBRARIES):
        return
    _check(cancelled)
    progress('native_prepare', 0, 0, 'Preparing the legacy libraries required by this Linux plug-in')
    tool = files('tux_access.resources') / 'prepare_arch_compat.sh'
    if not tool.is_file():
        raise InstallError('The native compatibility preparation tool is missing. Reinstall the launcher package.')
    if not Path('/etc/arch-release').is_file():
        raise InstallError('This native installation backend currently supports Arch Linux.')
    # These dependencies are fixed distribution packages, never arbitrary commands.
    import shutil
    if not all(shutil.which(name) for name in ('cmake', 'ninja', 'gcc', 'make', 'patchelf', 'bsdtar', 'gpgv')):
        progress('native_install', 0, 0, 'Authorize installation of the required Arch build tools')
        elevate = ['/usr/bin/pkexec'] if Path('/usr/bin/pkexec').is_file() else ['/usr/bin/sudo', '-n']
        command = elevate + ['/usr/bin/pacman', '-S', '--needed', '--noconfirm', 'python', 'cmake', 'ninja', 'gcc', 'make', 'patchelf', 'libarchive', 'gnupg']
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if result.returncode:
            raise InstallError('The system package manager could not prepare native installation tools. Use Advanced options for manual setup.')
    _check(cancelled)
    progress('native_prepare', 0, 0, 'Verifying and building the private compatibility libraries')
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(['/bin/bash', str(tool), '--managed'], stdout=output,
                                   stderr=output, start_new_session=True)
        deadline = time.monotonic() + 1200
        try:
            while process.poll() is None:
                _check(cancelled)
                if time.monotonic() > deadline:
                    raise InstallError('Compatibility preparation timed out. Use Advanced options for manual setup.')
                time.sleep(.1)
            if process.returncode:
                raise InstallError('Compatibility library preparation failed. Follow the native installation guide in Advanced options.')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
    _check(cancelled)


def install_product(product, token, settings, artifacts=None, progress=None, cancelled=None):
    settings = validate_settings(settings)
    progress = progress or (lambda stage, current, total, message: None)
    _check(cancelled)
    if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
        raise InstallError('Sign in before installing account products.')
    if artifacts is None:
        progress('metadata', 0, 0, 'Reading the authorized installer catalog')
        artifacts = available_artifacts(token)
    artifact, backend = select_artifact(product, artifacts, settings)
    if backend == 'wine':
        from tux_access.installation.backends import wine_spec
        wine_profile = wine_spec(product)
        manager = wine_profile.manager(settings, progress=progress, cancelled=cancelled)
        install_wine = getattr(manager, wine_profile.install_method)
        diagnostics = manager.preflight()
        missing_runtime = any(item.status == 'error' and item.code in ('wine', 'extractor', 'xwayland') for item in diagnostics)
        if missing_runtime and settings.wine_executable == 'wine' and Path('/etc/arch-release').is_file():
            _check(cancelled)
            progress('native_install', 0, 0, 'Authorize the required Wine runtime and installer tools')
            elevate = ['/usr/bin/pkexec'] if Path('/usr/bin/pkexec').is_file() else ['/usr/bin/sudo', '-n']
            result = subprocess.run(elevate + ['/usr/bin/pacman', '-S', '--needed', '--noconfirm', 'wine', '7zip', 'xorg-xwayland', 'mesa'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            if result.returncode:
                raise InstallError('The system package manager could not prepare Wine. Check Advanced runtime diagnostics before retrying.')
            _check(cancelled)
            diagnostics = manager.preflight()
        errors = [item.message for item in diagnostics if item.status == 'error']
        if errors:
            raise InstallError('Wine preparation required: ' + ' '.join(errors))
    _check(cancelled)
    progress('resolving', 0, 0, 'Resolving NI’s verified installer')
    spec = resolve_artifact(artifact, token)
    if backend == 'wine' and spec.sha256 != wine_profile.sha256:
        raise InstallError('The installer differs from the currently verified product build; it will not be installed.')
    destination = settings.download_directory / spec.name
    if destination.exists() or destination.is_symlink():
        _cached_download(destination, spec, progress, cancelled)
        path = destination
    else:
        progress('download', 0, spec.size, 'Downloading the original installer')
        path = download(spec, settings.download_directory, cancelled=cancelled,
                        progress=lambda current, total: progress('download', current, total, 'Downloading the original installer'))
    _check(cancelled)
    if backend == 'native':
        _prepare_native(progress, cancelled)
        from tux_access.installation.native.arch import install_verified_vst
        progress('native_install', 0, 0, 'Authorize the verified Linux package installation')
        result = install_verified_vst(path, spec.sha256)
        result = {**result, 'backend': 'native', 'status': 'Installed · activation unverified', 'activation': 'unverified'}
    else:
        result = install_wine(path)
        result = result.to_dict() if hasattr(result, 'to_dict') else dict(result)
    # No post-commit cancellation error: file installation is already complete.
    return {**result, 'path': str(path), 'sha256': spec.sha256, 'artifact': artifact}
