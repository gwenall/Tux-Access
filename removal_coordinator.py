"""Remove only launcher-owned application payloads, retaining user data.

Wine prefixes are private per application. Removal retains their other state
in a dated directory so user projects, preferences and content are preserved;
only the exact recorded original application files are unlinked. Native
packages are removed individually through pacman without dependency cleanup.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import uuid

from app_settings import validate_settings
from download_manager import DownloadCancelled
from launcher import product_values


class RemovalError(RuntimeError):
    pass


def _title(product):
    return ''.join(c for c in product_values(product)[0].casefold() if c.isalnum())


def can_uninstall(product, settings):
    if not isinstance(product, dict):
        return False
    native = {'ni-phasis': 'phasis', 'ni-reaktor': 'reaktor6'}
    if product.get('nativePackage') in native and product.get('source') == 'native-install':
        return _title(product) in (native[product['nativePackage']], 'reaktor6fx')
    from application_backends import wine_spec
    return (product.get('backend') == 'wine' and product.get('managed') is True
            and wine_spec(product) is not None)


def _emit(progress, stage, message, current=0, total=0):
    if progress:
        progress({'stage': stage, 'message': message, 'current': current, 'total': total})


def _cancel(cancelled):
    if cancelled and cancelled():
        raise DownloadCancelled('Uninstall cancelled; application files were retained.')


@contextmanager
def _parent(root_fd, parts):
    """Open a relative parent without following any symlink component."""
    descriptor = os.dup(root_fd)
    try:
        for name in parts:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if os.fstat(descriptor).st_uid != os.getuid():
                raise RemovalError('Application payload contains a foreign-owned directory.')
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _snapshot(prefix, hashes, progress, cancelled):
    from wine_manager import _relative
    identities = {}
    descriptor = os.open(prefix, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, (relative, expected) in enumerate(hashes.items(), 1):
            _cancel(cancelled)
            parts = ('drive_c', *_relative(relative).parts)
            with _parent(descriptor, parts[:-1]) as parent:
                file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                with os.fdopen(file_fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
                        raise RemovalError('Application payload contains a foreign or non-regular file.')
                    digest = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        _cancel(cancelled)
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                    if digest.hexdigest() != expected or _identity(before) != _identity(after):
                        raise RemovalError('An installed application file changed. It was preserved: ' + relative)
                    identities[relative] = _identity(after)
            if index % 100 == 0:
                _emit(progress, 'verifying_removal', 'Checking application files before removal', index, len(hashes))
    finally:
        os.close(descriptor)
    return identities


def _remove_wine(product, settings, progress, cancelled):
    from wine_manager import _ancestry, _directory, _publish_directory
    from application_backends import wine_spec
    spec = wine_spec(product)
    manager = spec.manager(settings)
    receipt_name = spec.receipt_name
    hashes = spec.load_hashes() if spec.load_hashes is not None else None
    valid = manager.installation_status()
    if not valid.get('installed') or any(product.get(key) != valid.get(key)
                                       for key in ('prefix', 'executable', 'receipt', 'version')):
        raise RemovalError('Uninstall requires the verified managed application record.')
    prefix = manager.prefix
    _ancestry(prefix)
    _directory(prefix)
    receipt = prefix / receipt_name
    if hashes is None:
        hashes = json.loads(receipt.read_text(encoding='utf-8'))['files']
    _emit(progress, 'verifying_removal', 'Checking the installed application before removal')
    identities = _snapshot(prefix, hashes, progress, cancelled)
    _cancel(cancelled)
    retained_root = manager.prefix_root / 'retained-data'
    _ancestry(retained_root.parent)
    retained_root.mkdir(mode=0o700, exist_ok=True)
    _directory(retained_root)
    if retained_root.stat().st_mode & 0o077:
        raise RemovalError('The retained-data directory must be private (permissions 0700).')
    destination = retained_root / (prefix.name + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    _emit(progress, 'removing', 'Closing this application and removing its installed files; retaining user data')
    manager._stop_prefix(manager._wine(), prefix, strict=True)
    _publish_directory(prefix, destination)
    descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Revalidate the complete set before the first unlink. Never traverse a
        # user-created link or recurse through unrelated files in the prefix.
        from wine_manager import _relative
        for relative, expected in identities.items():
            parts = ('drive_c', *_relative(relative).parts)
            with _parent(descriptor, parts[:-1]) as parent:
                if _identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != expected:
                    raise RemovalError('Application files changed during removal.')
        for relative in identities:
            parts = ('drive_c', *_relative(relative).parts)
            with _parent(descriptor, parts[:-1]) as parent:
                os.unlink(parts[-1], dir_fd=parent)
        os.unlink(receipt_name, dir_fd=descriptor)
    except Exception as error:
        raise RemovalError('Removal needs attention. Preserved state is at ' + str(destination)) from error
    finally:
        os.close(descriptor)
    return {'title': valid['title'], 'version': valid['version'], 'backend': 'wine',
            'status': 'uninstalled', 'retained_directory': str(destination)}


def _remove_native(product, settings, progress, cancelled):
    from arch_package import installed_products
    known = next((item for item in installed_products() if item.get('nativePackage') == product.get('nativePackage')), None)
    if known is None or not Path('/etc/arch-release').is_file():
        raise RemovalError('This launcher-owned native package is not installed on Arch Linux.')
    _cancel(cancelled)
    package = 'native-access-' + known['nativePackage']
    elevation = ['/usr/bin/pkexec'] if Path('/usr/bin/pkexec').is_file() else ['/usr/bin/sudo', '-n']
    _emit(progress, 'removing', 'Removing the application package; keeping content and shared dependencies')
    try:
        result = subprocess.run([*elevation, '/usr/bin/pacman', '-R', '--noconfirm', package],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    except (OSError, subprocess.SubprocessError):
        raise RemovalError('The package manager did not complete removal. Check pacman before retrying.') from None
    if result.returncode:
        raise RemovalError('Pacman could not remove this application package. Check permissions and package dependencies.')
    return {'title': known['title'], 'version': known['version'], 'backend': 'native', 'status': 'uninstalled'}


def uninstall_product(product, settings, progress=None, cancelled=None):
    settings = validate_settings(settings)
    if not can_uninstall(product, settings):
        raise RemovalError('Uninstall is available only for applications installed and managed by this launcher.')
    _cancel(cancelled)
    operation = _remove_wine if product.get('backend') == 'wine' else _remove_native
    result = operation(product, settings, progress, cancelled)
    from install_coordinator import installed_catalog
    try:
        result['_installed'] = installed_catalog(settings)
    except Exception:
        result['_installed'] = None
        result['_scan_warning'] = 'Application removed. Refresh the local installation list to complete the library update.'
    _emit(progress, 'complete', 'Application uninstalled; saved user data was retained', 1, 1)
    return result
