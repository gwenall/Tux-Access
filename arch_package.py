"""Build local Arch packages from verified NI Linux VST downloads.

Only the observed Phasis and Reaktor payload layouts are supported. NI code
is supplied by the user; it is never bundled with this independent launcher.
Debian maintainer scripts are not executed. NI-specific scanning and license
activation remain separate from pacman's file installation.
"""
import hashlib
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import os
import stat
import tarfile
import tempfile

from package_inspection import _elf, _members, inspect_deb

PROFILES = {
    'ni-phasis': ('Phasis', ('Phasis.so',)),
    'ni-reaktor': ('Reaktor 6', ('Reaktor 6.so', 'Reaktor 6 FX.so')),
}
COMPAT_LIBRARIES = ('libssl.so.1.1', 'libcrypto.so.1.1', 'libxerces-c-3.2.so')
COMPAT_PACKAGE = 'native-access-linux-compat'


class InstallationError(RuntimeError):
    pass


def _archive(path, files, metadata):
    """Write a local unsigned pacman archive, refusing existing destinations."""
    contents = {'.PKGINFO': (metadata.encode(), 0o644), **files}
    mtree = ['#mtree']
    for name, (payload, mode) in contents.items():
        escaped = ''.join(chr(value) if chr(value) in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:+-'
                          else '\\' + format(value, '03o') for value in ('./' + name).encode())
        mtree.append(f'{escaped} type=file uid=0 gid=0 mode={mode:o} time=0 size={len(payload)} sha256digest={hashlib.sha256(payload).hexdigest()}')
    contents['.MTREE'] = (gzip.compress(('\n'.join(mtree) + '\n').encode(), mtime=0), 0o644)
    with path.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:xz') as archive:
        for name, (payload, mode) in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            entry.mode = mode
            entry.uid = entry.gid = 0
            archive.addfile(entry, io.BytesIO(payload))
    return path


def _package_metadata(name, version, description, files, *, dependencies=(), license_name='custom'):
    lines = [f'pkgname = {name}', f'pkgbase = {name}', f'pkgver = {version}',
             f'pkgdesc = {description}', 'builddate = 0', 'packager = Local Tuxaccess',
             f'size = {sum(len(data) for data, _ in files.values())}',
             'arch = x86_64', f'license = {license_name}']
    lines.extend('depend = ' + value for value in dependencies)
    return '\n'.join(lines) + '\n'


def build_arch_vst_packages(package, expected_sha256, compat_directory, output_directory):
    """Prepare an auditable local install bundle; this function never elevates.

    expected_sha256 must come from the launcher's verified Metalink download.
    Compatibility libraries must be prepared from their trusted upstream sources.
    NI libraries get a local RPATH for these exact legacy ABIs; their original
    and installed hashes are recorded independently.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise InstallationError('A verified download SHA-256 is required.')
    package = Path(package)
    report = inspect_deb(package, expected_sha256)
    control = report['control']
    profile = PROFILES.get(control.get('Package'))
    version = control.get('Version', '')
    if profile is None or control.get('Architecture') != 'amd64':
        raise InstallationError('Only the inspected Phasis and Reaktor x86-64 Linux packages are supported.')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', version):
        raise InstallationError('Unsupported package version format.')
    title, plugins = profile
    exact = {'ni/registry/' + title + '.yaml', *(('usr/lib/vst/' + name) for name in plugins)}
    resource_prefix = 'usr/share/Native Instruments/' + title + '/'
    files = {}
    expanded = 0
    raw = package.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise InstallationError('The package changed during inspection.')
    for name, data in _members(raw).items():
        if not name.startswith('data.tar'):
            continue
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for entry in archive:
                relative = PurePosixPath(entry.name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise InstallationError('Unsafe package payload path.')
                name = str(relative)
                if entry.isdir():
                    continue
                if not entry.isfile() or (name not in exact and not name.startswith(resource_prefix)):
                    raise InstallationError('Unrecognized package payload entry.')
                if name in files or any(ord(c) < 32 for c in name):
                    raise InstallationError('Invalid or duplicate package payload entry.')
                expanded += entry.size
                if expanded > 256 * 1024 * 1024 or len(files) >= 10000:
                    raise InstallationError('Package payload exceeds installation limits.')
                files[name] = (archive.extractfile(entry).read(), 0o644)
    if not exact.issubset(files):
        raise InstallationError('Required plug-in or registry files are missing.')

    compat_directory = Path(compat_directory)
    compatibility = {}
    for name in COMPAT_LIBRARIES:
        path = compat_directory / name
        if path.stat().st_size > 32 * 1024 * 1024:
            raise InstallationError('Compatibility library exceeds size limit.')
        data = path.read_bytes()
        elf = _elf(data)
        if not elf or elf.get('machine') != 62 or elf.get('soname') != name:
            raise InstallationError('The compatibility library does not provide its required x86-64 ABI.')
        compatibility['usr/lib/native-access-linux/compat-legacy/' + name] = (data, 0o644)
    with tempfile.TemporaryDirectory() as temporary:
        for name in plugins:
            key = 'usr/lib/vst/' + name
            original = files[key][0]
            elf = _elf(original)
            if not elf or elf.get('machine') != 62 or 'VSTPluginMain' not in elf.get('plugin_entrypoints', []):
                raise InstallationError('The payload is not an inspected native x86-64 VST2 plug-in.')
            target = Path(temporary) / name
            target.write_bytes(original)
            try:
                subprocess.run(['/usr/bin/patchelf', '--force-rpath', '--set-rpath',
                                '$ORIGIN/../native-access-linux/compat-legacy', str(target)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            except (OSError, subprocess.SubprocessError):
                raise InstallationError('Could not configure the private plug-in library path.') from None
            files[key] = (target.read_bytes(), 0o644)

    manifest = {
        'package': control['Package'], 'title': title, 'version': version,
        'source_sha256': expected_sha256, 'activation': 'unverified',
        'debian_pre_depends': control.get('Pre-Depends', ''),
        'debian_maintainer_scripts_executed': False,
        'ni_plugin_info_integration': 'not implemented',
        'files': {name: hashlib.sha256(payload).hexdigest() for name, (payload, _) in {**files, **compatibility}.items()},
    }
    files['usr/share/native-access-linux/installed/' + control['Package'] + '.json'] = (
        (json.dumps(manifest, indent=2) + '\n').encode(), 0o644)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    compat_meta = _package_metadata(COMPAT_PACKAGE, '1.0-1', 'Private legacy ABI libraries for NI Linux VST testing',
                                    compatibility, dependencies=('glibc',), license_name='custom:OpenSSL Apache')
    plugin_name = 'native-access-' + control['Package']
    plugin_meta = _package_metadata(plugin_name, version + '-1', 'Locally converted NI ' + title + ' Linux VST payload', files,
                                   dependencies=(COMPAT_PACKAGE, 'glibc', 'gcc-libs', 'libarchive', 'libelf',
                                                 'freetype2', 'libpng', 'zlib', 'libjpeg-turbo', 'systemd-libs', 'harfbuzz'))
    compat_path = _archive(output / (COMPAT_PACKAGE + '-1.0-1-x86_64.pkg.tar.xz'), compatibility, compat_meta)
    plugin_path = _archive(output / (plugin_name + '-' + version + '-1-x86_64.pkg.tar.xz'), files, plugin_meta)
    return {'packages': [str(compat_path), str(plugin_path)], 'manifest': manifest,
            'notice': 'File installation does not establish NI activation or ni-plugin-info integration.'}


def _private_install_runtime(runtime=None):
    """Reject mutable staging ancestry before root opens local package paths."""
    runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid())))
    if not runtime.is_absolute() or '..' in runtime.parts:
        raise InstallationError('A private runtime directory is required for installation.')
    for component in reversed((runtime, *runtime.parents)):
        info = component.lstat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()) or
                (info.st_mode & 0o022 and not sticky_root)):
            raise InstallationError('Installation staging ancestry is not private.')
    info = runtime.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise InstallationError('Installation requires an owned private runtime directory.')
    return runtime


def install_verified_vst(package, expected_sha256, compat_directory=None):
    """Install a verified local payload with pacman, retaining package ownership.

    A desktop with Polkit uses its system authentication dialog. Minimal
    desktops can use an existing noninteractive sudo grant or the CLI route.
    """
    if not Path('/etc/arch-release').is_file():
        raise InstallationError('Native package installation currently supports Arch Linux only.')
    compat_directory = compat_directory or Path.home() / '.local/lib/native-access-linux/compat-legacy/lib'
    if not all((Path(compat_directory) / name).is_file() for name in COMPAT_LIBRARIES):
        raise InstallationError('The tested OpenSSL 1.1 and Xerces 3.2 compatibility libraries are required; see the installation guide.')
    runtime = _private_install_runtime()
    with tempfile.TemporaryDirectory(prefix='native-access-install-', dir=runtime) as directory:
        result = build_arch_vst_packages(package, expected_sha256, compat_directory, directory)
        try:
            elevation = (['/usr/bin/pkexec'] if Path('/usr/bin/pkexec').is_file()
                         else ['/usr/bin/sudo', '-n'])
            completed = subprocess.run([*elevation, '/usr/bin/pacman', '-U', '--noconfirm', *result['packages']],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        except (OSError, subprocess.SubprocessError):
            raise InstallationError('The native package manager did not complete the installation. Check pacman before retrying.') from None
        if completed.returncode:
            raise InstallationError('Pacman could not install the packages. Check the system authentication dialog, sudo access, package conflicts and the installation guide.')
        return result['manifest']


def installed_products(root=Path('/')):
    """Read our local installed records without claiming activation status."""
    products = []
    for path in (Path(root) / 'usr/share/native-access-linux/installed').glob('*.json'):
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            record = json.loads(path.read_text())
            if record.get('package') not in PROFILES or not isinstance(record.get('version'), str):
                continue
            title, plugins = PROFILES[record['package']]
            required = {'ni/registry/' + title + '.yaml', *(('usr/lib/vst/' + name) for name in plugins)}
            required.update('usr/lib/native-access-linux/compat-legacy/' + name for name in COMPAT_LIBRARIES)
            files = record.get('files', {})
            if not isinstance(files, dict):
                continue
            valid = required.issubset(files)
            for relative, expected in files.items():
                path_parts = PurePosixPath(relative)
                if path_parts.is_absolute() or '..' in path_parts.parts:
                    valid = False
                    break
                target = Path(root).joinpath(*path_parts.parts)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    valid = False
                    break
            products.append({'title': PROFILES[record['package']][0], 'version': record['version'],
                             'type': 'Native VST2', 'status': 'Installed · activation unverified' if valid else 'Installation needs repair',
                             'source': 'native-install', 'nativePackage': record['package']})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return products
