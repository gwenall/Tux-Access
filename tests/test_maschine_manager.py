from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from maschine_2184_plan import load_plan, load_hashes
from maschine_manager import (MaschineManager, ZIP_SHA256, ZIP_SIZE, SETUP_NAME,
                              EXE_TARGET, RECEIPT, VCREDIST_PATH,
                              PAYLOAD_COUNT, PAYLOAD_SIZE, validate_maschine_plan)
from wine_manager import WineError, WineCancelled


def settings(root):
    return SimpleNamespace(wine_prefix_directory=Path(root) / 'wine',
                           installation_directory=Path(root) / 'installation',
                           wine_executable='wine', yabridge_directory=None,
                           manage_wine=True, manual_mode=False)


class MaschineTests(unittest.TestCase):
    def test_complete_exact_manifest_and_primary_fingerprints(self):
        hashes = load_hashes()
        rows = validate_maschine_plan(load_plan(), hashes)
        self.assertEqual(len(rows), PAYLOAD_COUNT)
        self.assertEqual(sum(row['size'] for row in rows), PAYLOAD_SIZE)
        self.assertTrue(all(row['target'].startswith('Program Files/') for row in rows))
        self.assertEqual(hashes[EXE_TARGET], '29cbc4c6f085f1d0d8ac8ff6302d39a988085adf3e0c455360c369f536923216')

    def test_plan_rejects_paths_duplicate_destinations_and_changed_hash_coverage(self):
        for mutation in ('escape', 'duplicate', 'hash'):
            plan, hashes = load_plan(), load_hashes()
            if mutation == 'escape':
                plan['files'][0]['target'] = 'Program Files/../outside'
            elif mutation == 'duplicate':
                plan['files'][1]['target'] = plan['files'][0]['target'].upper()
            else:
                del hashes[EXE_TARGET]
            with self.subTest(mutation=mutation), self.assertRaises(WineError):
                validate_maschine_plan(plan, hashes)

    def test_wrong_artifact_never_initializes_wine_or_claims_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = MaschineManager(settings(temporary))
            archive = Path(temporary) / 'wrong.zip'
            archive.write_bytes(b'bad')
            with patch.object(manager, 'preflight', return_value=[]), \
                 patch.object(manager, '_prepare_display', side_effect=AssertionError('no display before verification')), \
                 patch('maschine_manager.ZIP_SIZE', 3):
                with self.assertRaisesRegex(WineError, 'Unsupported Maschine installer'):
                    manager.install_maschine_2184(archive)
            self.assertFalse(manager.prefix_root.exists())
            self.assertFalse(manager.installation_status()['installed'])

    def test_existing_prefix_is_preserved_before_runtime_or_payload_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = MaschineManager(settings(temporary))
            manager.prefix.mkdir(parents=True)
            sentinel = manager.prefix / 'preserve.txt'
            sentinel.write_text('existing')
            with patch.object(manager, 'preflight', return_value=[]), \
                 patch.object(manager, '_run', side_effect=AssertionError('no runtime work')):
                with self.assertRaisesRegex(WineError, 'already exists'):
                    manager.install_maschine_2184('irrelevant')
            self.assertEqual(sentinel.read_text(), 'existing')

    def run_fixture_pipeline(self, root, *, complete_boot=True, cancel_placing=False,
                             fail_registration=False):
        rows = [{'source': 'OFFLINE/a', 'target': EXE_TARGET, 'size': 3},
                {'source': 'OFFLINE/b', 'target': 'Program Files/Common Files/Native Instruments/Maschine 2/fixture.dat', 'size': 4}]
        payloads = {rows[0]['source']: b'exe', rows[1]['source']: b'data'}
        hashes = {row['target']: hashlib.sha256(payloads[row['source']]).hexdigest() for row in rows}
        def progress(stage, current, total, message):
            if cancel_placing and stage == 'placing':
                raise WineCancelled('Fixture cancellation')
        manager = MaschineManager(settings(root), progress=progress)
        archive = Path(root) / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr(SETUP_NAME, b'setup')
        runtime = b'redist'
        calls = []
        def run(argv, **options):
            calls.append(argv)
            if fail_registration and '/v' in argv and argv[argv.index('/v') + 1] == 'InstallVST64Dir':
                raise WineError('Fixture registration failure')
            if argv[1] == 'x':
                source = Path(next(value[2:] for value in argv if value.startswith('-o')))
                for relative, value in payloads.items():
                    file = source / 'data' / relative
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(value)
                file = source / VCREDIST_PATH
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(runtime)
            elif argv[1] == 'wineboot.exe':
                for architecture in (('system32', 'syswow64') if complete_boot else ('system32',)):
                    file = options['prefix'] / 'drive_c/windows' / architecture / 'kernel32.dll'
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b'MZ fixture')
            return 'wine-11.19' if argv[1] == '--version' else ''
        context = ExitStack()
        context.enter_context(patch.object(manager, 'preflight', return_value=[]))
        context.enter_context(patch.object(manager, '_prepare_display'))
        context.enter_context(patch.object(manager, '_wine', return_value='/fixture/wine'))
        context.enter_context(patch.object(manager, '_run', side_effect=run))
        context.enter_context(patch.object(manager, '_stop_prefix'))
        values = {'ZIP_SIZE': archive.stat().st_size, 'ZIP_SHA256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                  'SETUP_SIZE': 5, 'SETUP_SHA256': hashlib.sha256(b'setup').hexdigest(),
                  'VCREDIST_SIZE': len(runtime), 'VCREDIST_SHA256': hashlib.sha256(runtime).hexdigest()}
        for key, value in values.items():
            context.enter_context(patch('maschine_manager.' + key, value))
        context.enter_context(patch('maschine_manager.load_plan', return_value={'files': rows}))
        context.enter_context(patch('maschine_manager.load_hashes', return_value=hashes))
        context.enter_context(patch('maschine_manager.validate_maschine_plan', return_value=rows))
        context.enter_context(patch('maschine_manager.shutil.which', return_value='/fixture/7z'))
        context.enter_context(patch('maschine_manager.shutil.disk_usage', return_value=SimpleNamespace(free=10 * 1024**3)))
        context.enter_context(patch('maschine_manager._archive_members', return_value=[{'Path': 'fixture', 'Size': '1'}] * 819))
        context.enter_context(patch('maschine_manager._publish_directory', side_effect=lambda source, target: source.rename(target)))
        return context, manager, archive, hashes, calls

    def test_success_requires_complete_boot_and_original_payload_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, manager, archive, hashes, calls = self.run_fixture_pipeline(temporary)
            with context:
                result = manager.install_maschine_2184(archive)
                self.assertEqual(result.title, 'Maschine 2')
                self.assertEqual(result.activation, 'unverified')
                self.assertTrue(manager.installation_status()['installed'])
                receipt = json.loads((manager.prefix / RECEIPT).read_text())
                self.assertEqual(receipt['files'], hashes)
                self.assertEqual(receipt['factory_libraries'], 'not installed by this adapter')
                self.assertTrue(any(call[1] == 'wineboot.exe' for call in calls))
                self.assertFalse(any(call[0] == '/fixture/wine' and 'Setup PC.exe' in call[1] for call in calls))

    def test_registration_writes_only_original_two_64_bit_install_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, manager, archive, hashes, calls = self.run_fixture_pipeline(temporary)
            with context:
                manager.install_maschine_2184(archive)
                registrations = [call for call in calls if '/reg:64' in call]
                expected = [
                    ['/fixture/wine', 'reg', 'add', r'HKLM\SOFTWARE\Native Instruments\Maschine 2',
                     '/v', 'InstallDir', '/t', 'REG_SZ', '/d',
                     'C:\\Program Files\\Native Instruments\\Maschine 2\\', '/f', '/reg:64'],
                    ['/fixture/wine', 'reg', 'add', r'HKLM\SOFTWARE\Native Instruments\Maschine 2',
                     '/v', 'InstallVST64Dir', '/t', 'REG_SZ', '/d',
                     'C:\\Program Files\\Native Instruments\\VSTPlugins 64 bit\\', '/f', '/reg:64'],
                ]
                self.assertEqual(registrations, expected)
                calls.clear()
                manager.register_installation_paths()
                self.assertEqual(calls, expected)

    def test_registration_failure_rolls_back_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, manager, archive, hashes, calls = self.run_fixture_pipeline(temporary, fail_registration=True)
            with context:
                with self.assertRaisesRegex(WineError, 'registration failure'):
                    manager.install_maschine_2184(archive)
            self.assertFalse(manager.prefix.exists())
            self.assertEqual(list(manager.prefix_root.iterdir()), [])

    def test_registration_refuses_arbitrary_prefix_without_running_wine(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = MaschineManager(settings(temporary))
            with patch.object(manager, '_run', side_effect=AssertionError('must not execute')):
                with self.assertRaisesRegex(WineError, 'managed Maschine prefix'):
                    manager.register_installation_paths(prefix=Path(temporary) / 'imported')

    def test_zero_boot_exit_with_incomplete_prefix_is_not_install_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, manager, archive, hashes, calls = self.run_fixture_pipeline(temporary, complete_boot=False)
            with context:
                with self.assertRaisesRegex(WineError, 'required syswow64 system files'):
                    manager.install_maschine_2184(archive)
            self.assertFalse(manager.prefix.exists())
            self.assertEqual(list(manager.prefix_root.iterdir()), [])

    def test_cancellation_rolls_back_entire_staged_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            context, manager, archive, hashes, calls = self.run_fixture_pipeline(temporary, cancel_placing=True)
            with context:
                with self.assertRaises(WineCancelled):
                    manager.install_maschine_2184(archive)
            self.assertFalse(manager.prefix.exists())
            self.assertEqual(list(manager.prefix_root.iterdir()), [])

    def test_receipt_alone_and_arbitrary_record_never_authorize_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = MaschineManager(settings(temporary))
            manager.prefix.mkdir(parents=True)
            (manager.prefix / RECEIPT).write_text(json.dumps({'status': 'installed'}))
            self.assertFalse(manager.installation_status()['installed'])
            record = {'title': 'Maschine 2', 'version': '2.18.4', 'backend': 'wine', 'managed': True,
                      'prefix': '/tmp/imported-prefix', 'executable': '/tmp/imported.exe', 'receipt': '/tmp/imported.json'}
            with patch('maschine_manager.subprocess.Popen', side_effect=AssertionError('must not execute')):
                with self.assertRaises(WineError):
                    manager.launch_record(record)


if __name__ == '__main__':
    unittest.main()
