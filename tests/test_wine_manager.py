import io
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import sys
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch
from unittest.mock import Mock

from kontakt_890_plan import load_plan
from wine_manager import (WineManager, WineError, WineCancelled, _archive_members,
                          _place_files, _publish_directory, validate_plan,
                          ZIP_SHA256, ZIP_SIZE, PAYLOAD_COUNT, PAYLOAD_SIZE,
                          EXE_TARGET, VST3_TARGET)


def settings(root):
    return SimpleNamespace(wine_prefix_directory=Path(root) / 'wine',
                           installation_directory=Path(root) / 'installation',
                           wine_executable='wine', yabridge_directory=None,
                           manage_wine=True, manual_mode=False)


class WineManagerTests(unittest.TestCase):
    def legacy_fixture(self, root):
        manager = WineManager(settings(root))
        prefix = manager.settings.installation_directory / 'wine-kontakt-8-wow64'
        rows, hashes = [], {}
        for target, value in ((EXE_TARGET, b'fixture exe'), (VST3_TARGET, b'fixture vst3'),
                              ('ProgramData/Native Instruments/Kontakt 8/fixture.dat', b'fixture data')):
            path = prefix / 'drive_c' / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
            rows.append({'source': 'OFFLINE/' + path.name, 'target': target, 'size': len(value)})
            hashes[target] = hashlib.sha256(value).hexdigest()
        home = Path(root) / 'home'
        receipt = home / '.cache/native-access-linux/kontakt-installer/payload-placement-receipt.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({'installer_sha256': ZIP_SHA256, 'version': '8.9.0', 'files': hashes}))
        receipt.chmod(0o600)
        return manager, prefix, home, receipt, rows

    def test_legacy_is_read_only_full_manifest_verified_and_activation_unverified(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager, prefix, home, receipt, rows = self.legacy_fixture(temporary)
            original = receipt.read_bytes()
            files_before = sorted(str(path.relative_to(prefix)) for path in prefix.rglob('*'))
            with patch('wine_manager.Path.home', return_value=home), \
                 patch('wine_manager.LEGACY_RECEIPT_SHA256', hashlib.sha256(original).hexdigest()), \
                 patch('wine_manager.validate_plan', return_value=rows):
                record = manager.detect_legacy_installation()
            self.assertTrue(record['installed'])
            self.assertFalse(record['managed'])
            self.assertEqual(record['activation'], 'unverified')
            self.assertEqual(record['prefix'], str(prefix))
            self.assertEqual(receipt.read_bytes(), original)
            self.assertEqual(sorted(str(path.relative_to(prefix)) for path in prefix.rglob('*')), files_before)
            self.assertFalse(manager.prefix.exists())

    def test_legacy_tampered_primary_and_changed_receipt_are_not_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager, prefix, home, receipt, rows = self.legacy_fixture(temporary)
            original = receipt.read_bytes()
            with patch('wine_manager.Path.home', return_value=home), \
                 patch('wine_manager.LEGACY_RECEIPT_SHA256', hashlib.sha256(original).hexdigest()), \
                 patch('wine_manager.validate_plan', return_value=rows):
                executable = prefix / 'drive_c' / EXE_TARGET
                executable.write_bytes(b'changed exe')
                self.assertEqual(len(executable.read_bytes()), rows[0]['size'])
                status = manager.detect_legacy_installation()
                self.assertFalse(status['installed'])
                self.assertIn('file changed', status['message'])
                executable.write_bytes(b'fixture exe')
                content = prefix / 'drive_c' / rows[2]['target']
                content.write_bytes(b'changed data')
                self.assertEqual(len(content.read_bytes()), rows[2]['size'])
                status = manager.detect_legacy_installation()
                self.assertFalse(status['installed'])
                self.assertIn('file changed', status['message'])
                receipt.write_text('[]')
                status = manager.detect_legacy_installation()
                self.assertFalse(status['installed'])
                self.assertIn('receipt changed', status['message'])

    def test_legacy_launch_rejects_record_paths_outside_the_known_verified_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager, prefix, home, receipt, rows = self.legacy_fixture(temporary)
            with patch('wine_manager.Path.home', return_value=home), \
                 patch('wine_manager.LEGACY_RECEIPT_SHA256', hashlib.sha256(receipt.read_bytes()).hexdigest()), \
                 patch('wine_manager.validate_plan', return_value=rows), \
                 patch.object(manager, '_prepare_display'), \
                 patch.object(manager, '_wine', return_value='/fixture/wine'), \
                 patch('wine_manager.subprocess.Popen') as process:
                record = manager.detect_legacy_installation()
                with self.assertRaisesRegex(WineError, 'does not match'):
                    manager.launch_record({**record, 'executable': '/tmp/imported.exe'})
                process.assert_not_called()
                manager.launch_record(record)
                self.assertEqual(process.call_args.args[0][1], str(prefix / 'drive_c' / EXE_TARGET))
                self.assertEqual(process.call_args.kwargs['env']['WINEPREFIX'], str(prefix))
                self.assertNotIn('mscoree', process.call_args.kwargs['env']['WINEDLLOVERRIDES'])

    def test_complete_original_plan_is_pinned_and_has_expected_targets(self):
        rows = validate_plan(load_plan())
        self.assertEqual(len(rows), PAYLOAD_COUNT)
        self.assertEqual(sum(row['size'] for row in rows), PAYLOAD_SIZE)
        self.assertEqual(rows[0]['target'], 'Program Files/Native Instruments/Kontakt 8/Kontakt 8.exe')

    def test_plan_rejects_traversal_duplicate_target_and_wrong_types(self):
        for mutation in ('traversal', 'duplicate', 'size'):
            plan = load_plan()
            if mutation == 'traversal':
                plan['files'][0]['source'] = 'OFFLINE/../escape'
            elif mutation == 'duplicate':
                plan['files'][1]['target'] = plan['files'][0]['target'].upper()
            else:
                plan['files'][0]['size'] = True
            with self.subTest(mutation=mutation), self.assertRaises(WineError):
                validate_plan(plan)

    def test_archive_rejects_escape_links_duplicates_and_excessive_bytes(self):
        unsafe = ['Path = ../escape\nSize = 1\n',
                  'Path = data/file\nSize = 1\nSymbolic Link = /tmp\n',
                  'Path = data/F\nSize = 1\n\nPath = data/f\nSize = 1\n',
                  'Path = data/file\nSize = 999999999999\n',
                  'Path = C:\\escape\nSize = 1\n']
        for listing in unsafe:
            with self.subTest(listing=listing), self.assertRaises(WineError):
                _archive_members(listing)
        self.assertEqual(len(_archive_members('Path = data/file\nSize = 3\nAttributes = A\nEncrypted = -\n')), 1)

    def test_placement_verifies_hash_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'source', root / 'target'
            (source / 'OFFLINE').mkdir(parents=True)
            target.mkdir()
            (source / 'OFFLINE/a').write_bytes(b'original')
            rows = [{'source': 'OFFLINE/a', 'target': 'Program Files/a', 'size': 8}]
            receipt = _place_files(source, target, rows)
            self.assertEqual((target / 'Program Files/a').read_bytes(), b'original')
            self.assertEqual(len(receipt['Program Files/a']), 64)
            with self.assertRaisesRegex(WineError, 'refusing overwrite'):
                _place_files(source, target, rows)
            self.assertEqual((target / 'Program Files/a').read_bytes(), b'original')

    def test_cancel_rolls_back_created_files_and_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'source', root / 'target'
            (source / 'OFFLINE').mkdir(parents=True)
            target.mkdir()
            (target / 'keep.txt').write_bytes(b'keep')
            (source / 'OFFLINE/a').write_bytes(b'a' * 32)
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                return calls >= 3
            with self.assertRaises(WineCancelled):
                _place_files(source, target, [{'source': 'OFFLINE/a', 'target': 'Program Files/a', 'size': 32}], cancelled=cancel)
            self.assertEqual(list(target.iterdir()), [target / 'keep.txt'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink/ownership safety')
    def test_symlink_target_ancestry_never_writes_outside_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target, outside = root / 'source', root / 'target', root / 'outside'
            (source / 'OFFLINE').mkdir(parents=True)
            target.mkdir()
            outside.mkdir()
            (source / 'OFFLINE/a').write_bytes(b'original')
            (target / 'Program Files').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(WineError):
                _place_files(source, target, [{'source': 'OFFLINE/a', 'target': 'Program Files/a', 'size': 8}])
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(platform.system() == 'Linux', 'Linux exclusive publication')
    def test_publication_never_replaces_even_empty_existing_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'stage', root / 'prefix'
            source.mkdir()
            (source / 'a').write_text('original')
            target.mkdir()
            with self.assertRaisesRegex(WineError, 'already exists'):
                _publish_directory(source, target)
            self.assertTrue((source / 'a').exists())
            self.assertEqual(list(target.iterdir()), [])
            target.rmdir()
            _publish_directory(source, target)
            self.assertTrue((target / 'a').exists())
            self.assertFalse(source.exists())

    def test_existing_prefix_rejected_before_installer_or_runtime_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            manager.prefix.mkdir(parents=True)
            sentinel = manager.prefix / 'manual.txt'
            sentinel.write_text('preserve')
            with patch.object(manager, 'preflight', return_value=[]), patch.object(manager, '_run', side_effect=AssertionError('must not run')):
                with self.assertRaisesRegex(WineError, 'already exists'):
                    manager.install_kontakt_890(Path(temporary) / 'absent.zip')
            self.assertEqual(sentinel.read_text(), 'preserve')

    def test_missing_or_incomplete_install_never_claims_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            status = manager.installation_status()
            self.assertFalse(status['installed'])
            self.assertEqual(status['activation'], 'unverified')
            manager.prefix.mkdir(parents=True)
            status = manager.installation_status()
            self.assertEqual(status['status'], 'needs repair')
            self.assertFalse(status['installed'])
            self.assertEqual(manager.installed_products(), [])
            (manager.prefix / '.native-access-linux-kontakt.json').write_text('[]')
            self.assertEqual(manager.installation_status()['status'], 'needs repair')

    def test_disabled_management_never_runs_or_creates_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(temporary)
            config.manage_wine = False
            manager = WineManager(config)
            with patch.object(manager, 'preflight', side_effect=AssertionError('must not run')):
                with self.assertRaisesRegex(WineError, 'disabled'):
                    manager.install_kontakt_890('irrelevant')
            self.assertFalse(manager.prefix_root.exists())

    def test_publication_shutdown_accepts_already_exited_wineserver_but_requires_wait_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            with patch('wine_manager.Path.is_file', return_value=True), \
                 patch('wine_manager.subprocess.run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]) as run:
                manager._stop_prefix('/fixture/wine', manager.prefix, strict=True)
            self.assertEqual([call.args[0][1] for call in run.call_args_list], ['-k', '-w'])
            with patch('wine_manager.Path.is_file', return_value=True), \
                 patch('wine_manager.subprocess.run', side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=1)]):
                with self.assertRaisesRegex(WineError, 'Cannot stop'):
                    manager._stop_prefix('/fixture/wine', manager.prefix, strict=True)

    def test_wrong_artifact_fails_before_managed_prefix_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            installer = Path(temporary) / 'bad.zip'
            installer.write_bytes(b'bad')
            with patch.object(manager, 'preflight', return_value=[]), patch('wine_manager.ZIP_SIZE', 3):
                with self.assertRaisesRegex(WineError, 'Unsupported installer'):
                    manager.install_kontakt_890(installer)
            self.assertFalse(manager.prefix_root.exists())

    def test_prefix_initialization_failure_discards_the_entire_staged_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = WineManager(settings(root))
            installer = root / 'fixture.zip'
            with zipfile.ZipFile(installer, 'w') as archive:
                archive.writestr('Kontakt 8 8.9.0 Setup PC.exe', b'exe')
            expected = hashlib.sha256(installer.read_bytes()).hexdigest()
            runtime = b'redist'
            boot_succeeds = False
            def run(argv, **options):
                if argv[1] == 'x':
                    extracted = Path(next(value[2:] for value in argv if value.startswith('-o')))
                    (extracted / 'data/OFFLINE/mFileBagIDE.dll/bag').mkdir(parents=True)
                    (extracted / 'data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe').write_bytes(runtime)
                    return ''
                if argv[1] == 'wineboot.exe':
                    prefix = options['prefix']
                    (prefix / 'drive_c').mkdir()
                    (prefix / 'user.reg').write_text('partial runtime initialization')
                    if boot_succeeds:
                        return ''
                    raise WineError('Fixture wineboot failed')
                return ''
            with patch.object(manager, 'preflight', return_value=[]), \
                 patch.object(manager, '_prepare_display'), \
                 patch.object(manager, '_wine', return_value='/fixture/wine'), \
                 patch.object(manager, '_run', side_effect=run), \
                 patch.object(manager, '_stop_prefix'), \
                 patch('wine_manager.shutil.which', return_value='/fixture/7z'), \
                 patch('wine_manager.shutil.disk_usage', return_value=SimpleNamespace(free=20 * 1024**3)), \
                 patch('wine_manager.ZIP_SHA256', expected), \
                 patch('wine_manager.ZIP_SIZE', installer.stat().st_size), \
                 patch('wine_manager.SETUP_SIZE', 3), \
                 patch('wine_manager.VCREDIST_SIZE', len(runtime)), \
                 patch('wine_manager.VCREDIST_SHA256', hashlib.sha256(runtime).hexdigest()), \
                 patch('wine_manager._archive_members', return_value=[{'Path': 'fixture', 'Size': '1'}] * 8148):
                with self.assertRaisesRegex(WineError, 'Fixture wineboot failed'):
                    manager.install_kontakt_890(installer)
                boot_succeeds = True
                with self.assertRaisesRegex(WineError, 'required system32 system files'):
                    manager.install_kontakt_890(installer)
            self.assertFalse(manager.prefix.exists())
            self.assertEqual(list(manager.prefix_root.iterdir()), [])
            self.assertEqual(hashlib.sha256(installer.read_bytes()).hexdigest(), expected)

    def test_environment_excludes_inherited_wine_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            with patch.dict(os.environ, {'WINEPREFIX': '/other', 'WINEDLLOVERRIDES': 'bad', 'WINELOADER': 'bad', 'DISPLAY': ':5'}):
                env = manager._env(manager.prefix)
            self.assertEqual(env['WINEPREFIX'], str(manager.prefix))
            self.assertEqual(env['WINEARCH'], 'wow64')
            self.assertEqual(env['DISPLAY'], ':5')
            self.assertEqual(env['WINEDLLOVERRIDES'], 'winemenubuilder.exe=d')
            self.assertNotIn('WINELOADER', env)

    def test_bootstrap_heartbeat_reports_elapsed_work_without_fake_percentage(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            manager = WineManager(settings(temporary), progress=lambda *values: events.append(values))
            process = Mock(returncode=0)
            process.poll.side_effect = [None, None, 0, 0]
            with patch('wine_manager.subprocess.Popen', return_value=process), \
                 patch('wine_manager.time.monotonic', side_effect=[0, 11, 22]), \
                 patch('wine_manager.time.sleep'):
                manager._run(['/fixture/wine', 'wineboot.exe', '--init'], prefix=manager.prefix, timeout=300)
            self.assertEqual(len(events), 2)
            self.assertTrue(all(event[:3] == ('initializing', 0, 0) for event in events))
            self.assertIn('11 s', events[0][3])
            self.assertIn('22 s', events[1][3])

    def test_optional_bootstrap_suppression_is_restricted_to_initialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            initialization = manager._env(manager.prefix, initializing=True)
            self.assertEqual(initialization['WINEDLLOVERRIDES'], 'winemenubuilder.exe=d;mscoree,mshtml=')
            with patch.object(manager, 'installation_status', return_value={'status': 'installed'}), \
                 patch.object(manager, '_prepare_display'), \
                 patch.object(manager, '_wine', return_value='/fixture/wine'), \
                 patch('wine_manager.subprocess.Popen') as process:
                manager.launch_kontakt()
            launch = process.call_args.kwargs['env']
            self.assertEqual(launch['WINEDLLOVERRIDES'], 'winemenubuilder.exe=d')
            self.assertNotIn('mscoree', launch['WINEDLLOVERRIDES'])
            self.assertNotIn('mshtml', launch['WINEDLLOVERRIDES'])

    def test_bridge_selects_exact_directory_not_path_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(temporary)
            config.yabridge_directory = Path(temporary) / 'bridge'
            config.yabridge_directory.mkdir()
            for name in ('yabridgectl', 'yabridge-host.exe', 'libyabridge-vst3.so'):
                (config.yabridge_directory / name).write_bytes(b'fixture')
            manager = WineManager(config)
            with patch.object(manager, '_run', return_value='yabridgectl b580a9f7') as run:
                diagnostics = manager._bridge_diagnostics()
            self.assertEqual(run.call_args.args[0][0], str(config.yabridge_directory / 'yabridgectl'))
            self.assertIn(str(config.yabridge_directory / 'yabridge-host.exe'), diagnostics[0].message)
            self.assertIn('must be tested', diagnostics[0].message)

    @unittest.skipUnless(os.name == 'posix', 'Linux private diagnostic permissions')
    def test_only_prefix_initialization_retains_bounded_private_failure_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = WineManager(settings(temporary))
            manager.prefix_root.mkdir(mode=0o700)
            prefix = manager.prefix_root / 'fixture-prefix'
            prefix.mkdir()
            with self.assertRaises(WineError):
                manager._run([sys.executable, '-c', 'raise SystemExit(2)'], prefix=prefix, timeout=15)
            self.assertFalse((manager.prefix_root / '.diagnostics').exists())
            # Python rejects this nonexistent input, providing deterministic output
            # without executing Wine or an installer in a unit test.
            with self.assertRaises(WineError):
                manager._run([sys.executable, 'wineboot'], prefix=prefix, timeout=15)
            log = Path(manager._last_initialization_log)
            self.assertTrue(log.is_file())
            self.assertLess(log.stat().st_size, 66 * 1024)
            if os.name == 'posix':
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                self.assertEqual(log.parent.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
