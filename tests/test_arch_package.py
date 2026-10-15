import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from tux_access.installation.native.arch import build_arch_vst_packages, InstallationError
from test_package_inspection import archive, member


def fixture(extra=None):
    files = {'usr/lib/vst/Phasis.so': b'fixture-plugin',
             'ni/registry/Phasis.yaml': b'fixture-registry',
             'usr/share/Native Instruments/Phasis/preset.nksfx': b'fixture-preset'}
    if extra: files.update(extra)
    control = archive({'control': b'Package: ni-phasis\nVersion: 1.2.1\nArchitecture: amd64\nPre-Depends: ni-plugin-info\n',
                       'postinst': b'#!/bin/sh\nexit 99\n'})
    return b'!<arch>\n' + member('debian-binary', b'2.0\n') + member('control.tar.xz', control) + member('data.tar.xz', archive(files))


class ArchPackageTests(unittest.TestCase):
    def test_traversal_and_unrecognized_system_files_rejected_before_commands(self):
        for name in ('../../etc/shadow', '/etc/shadow', 'etc/profile', 'usr/share/Native Instruments/Phasis/../other'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                package = Path(directory) / 'fixture.deb'
                package.write_bytes(fixture({name: b'reject'}))
                with patch('tux_access.installation.native.arch.subprocess.run', side_effect=AssertionError('Must not run command')):
                    with self.assertRaises(InstallationError):
                        build_arch_vst_packages(package, hashlib.sha256(package.read_bytes()).hexdigest(), directory, Path(directory) / 'out')
                self.assertFalse((Path(directory) / 'out').exists())

    def test_build_records_changes_and_omits_scripts_and_world_writable_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'fixture.deb'
            package.write_bytes(fixture())
            for name in ('libssl.so.1.1', 'libcrypto.so.1.1', 'libxerces-c-3.2.so'):
                (root / name).write_bytes(name.encode())
            def elf(payload):
                text = payload.decode()
                if text.startswith('lib'):return {'machine': 62, 'soname': text}
                return {'machine': 62, 'plugin_entrypoints': ['VSTPluginMain']}
            def configure(command, **kwargs):
                path = Path(command[-1]); path.write_bytes(path.read_bytes() + b'-rpath')
            with patch('tux_access.installation.native.arch._elf', side_effect=elf), patch('tux_access.installation.native.arch.subprocess.run', side_effect=configure) as process:
                result = build_arch_vst_packages(package, hashlib.sha256(package.read_bytes()).hexdigest(), root, root / 'out')
            self.assertEqual(process.call_count, 1)
            self.assertFalse(result['manifest']['debian_maintainer_scripts_executed'])
            self.assertEqual(result['manifest']['activation'], 'unverified')
            with tarfile.open(result['packages'][1]) as archive_file:
                names = archive_file.getnames()
                self.assertNotIn('postinst', names)
                self.assertNotIn('.INSTALL', names)
                registry = archive_file.getmember('ni/registry/Phasis.yaml')
                self.assertEqual(registry.mode, 0o644)
                binary = archive_file.extractfile('usr/lib/vst/Phasis.so').read()
                self.assertEqual(result['manifest']['files']['usr/lib/vst/Phasis.so'], hashlib.sha256(binary).hexdigest())
            with self.assertRaises(FileExistsError), patch('tux_access.installation.native.arch._elf', side_effect=elf), patch('tux_access.installation.native.arch.subprocess.run', side_effect=configure):
                build_arch_vst_packages(package, hashlib.sha256(package.read_bytes()).hexdigest(), root, root / 'out')

    def test_incorrect_compatibility_abi_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'fixture.deb'; package.write_bytes(fixture())
            (root / 'libssl.so.1.1').write_bytes(b'wrong-ABI')
            with patch('tux_access.installation.native.arch._elf', return_value={'machine': 62, 'soname': 'libssl.so.3'}):
                with self.assertRaises(InstallationError):
                    build_arch_vst_packages(package, hashlib.sha256(package.read_bytes()).hexdigest(), root, root / 'out')
            self.assertFalse((root / 'out').exists())



class InstalledRecordTests(unittest.TestCase):
    def test_missing_or_changed_compatibility_cannot_report_installed(self):
        import json
        from tux_access.installation.native.arch import installed_products, COMPAT_LIBRARIES
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = {}
            paths = ['ni/registry/Phasis.yaml', 'usr/lib/vst/Phasis.so'] + ['usr/lib/native-access-linux/compat-legacy/' + name for name in COMPAT_LIBRARIES]
            for relative in paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test-content')
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = root / 'usr/share/native-access-linux/installed/ni-phasis.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'package':'ni-phasis', 'version':'1.2.1', 'files':hashes}))
            self.assertIn('Installed', installed_products(root)[0]['status'])
            library = root / paths[-1]
            library.write_bytes(b'changed')
            self.assertEqual(installed_products(root)[0]['status'], 'Installation needs repair')
            library.unlink()
            self.assertEqual(installed_products(root)[0]['status'], 'Installation needs repair')

    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX staging required')
    def test_shared_and_symlink_runtime_rejected(self):
        from tux_access.installation.native.arch import _private_install_runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'; runtime.mkdir(mode=0o700)
            self.assertEqual(_private_install_runtime(runtime), runtime)
            runtime.chmod(0o777)
            with self.assertRaises(InstallationError): _private_install_runtime(runtime)
            runtime.chmod(0o700)
            link = root / 'link'; link.symlink_to(runtime, target_is_directory=True)
            with self.assertRaises(InstallationError): _private_install_runtime(link)
            parent = root / 'shared'; parent.mkdir(mode=0o777); parent.chmod(0o777)
            child = parent / 'private'; child.mkdir(mode=0o700)
            with self.assertRaises(InstallationError): _private_install_runtime(child)




class InstallerCleanupTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX staging required')
    def test_system_authentication_uses_only_fixed_pacman_command(self):
        from tux_access.installation.native.arch import install_verified_vst
        import subprocess
        for polkit in (True, False):
            with self.subTest(polkit=polkit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package_path = str(root / 'prepared.pkg.tar.xz')
                def available(path):
                    return polkit if str(path) == '/usr/bin/pkexec' else True
                with patch('tux_access.installation.native.arch.Path.is_file', available), \
                     patch('tux_access.installation.native.arch._private_install_runtime', return_value=root), \
                     patch('tux_access.installation.native.arch.build_arch_vst_packages', return_value={'packages': [package_path], 'manifest': {'title': 'fixture'}}), \
                     patch('tux_access.installation.native.arch.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as process:
                    install_verified_vst('fixture', 'a' * 64, root)
                expected = ['/usr/bin/pkexec'] if polkit else ['/usr/bin/sudo', '-n']
                self.assertEqual(process.call_args.args[0], expected + ['/usr/bin/pacman', '-U', '--noconfirm', package_path])
                self.assertNotIn('shell', process.call_args.kwargs)

    @unittest.skipUnless(__import__('os').name == 'posix', 'POSIX staging required')
    def test_private_package_staging_cleaned_after_success_and_failure(self):
        from tux_access.installation.native.arch import install_verified_vst
        import subprocess
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                def build(package, digest, compatibility, staging):
                    target = Path(staging) / 'local.pkg.tar.xz'; target.write_bytes(b'fixture')
                    return {'packages':[str(target)], 'manifest':{'title':'fixture'}}
                with patch('tux_access.installation.native.arch.Path.is_file', return_value=True), patch('tux_access.installation.native.arch._private_install_runtime', return_value=root), patch('tux_access.installation.native.arch.build_arch_vst_packages', side_effect=build), patch('tux_access.installation.native.arch.subprocess.run', return_value=subprocess.CompletedProcess([],exit_code)):
                    if exit_code:
                        with self.assertRaises(InstallationError):install_verified_vst('fixture','a'*64,root)
                    else:
                        self.assertEqual(install_verified_vst('fixture','a'*64,root)['title'], 'fixture')
                self.assertEqual(list(root.iterdir()), [])

if __name__ == '__main__': unittest.main()
