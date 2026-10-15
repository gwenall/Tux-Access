from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from ni_application_manager import (ApplicationProfile, BundledRuntime, InstallerArtifact,
                                    NiApplicationManager, PublicRegistryValue, validate_payload)
from wine_manager import WineError, WineCancelled


def digest(value): return hashlib.sha256(value).hexdigest()


class ApplicationManagerTests(unittest.TestCase):
    def fixture(self, root, *, runtime=True, broken_boot=False, source_tamper=False,
                registration_failure=False, cancel_stage=None):
        archive = Path(root)/'original.zip'
        with zipfile.ZipFile(archive, 'w') as stream: stream.writestr('Fixture Setup PC.exe', b'original setup')
        rows = [{'source': 'OFFLINE/a/Fixture.exe', 'target': 'Program Files/Native Instruments/Fixture/Fixture.exe', 'size': 3},
                {'source': 'OFFLINE/b/preset.bin', 'target': 'Program Files (x86)/Common Files/Native Instruments/Fixture/preset.bin', 'size': 4}]
        payloads = {rows[0]['source']: b'exe', rows[1]['source']: b'data'}
        hashes = {row['target']: digest(payloads[row['source']]) for row in rows}
        profile = ApplicationProfile('fixture', 'Fixture', '1.0.0', 'public-id',
            InstallerArtifact(archive.stat().st_size, digest(archive.read_bytes()), 'Fixture Setup PC.exe', 14, digest(b'original setup'), 3),
            '1'*64, '2'*64, 2, 7, rows[0]['target'],
            ('Program Files/Native Instruments/Fixture', 'Program Files (x86)/Common Files/Native Instruments/Fixture'),
            lambda: {'files': [dict(row) for row in rows], 'unresolved': [], 'skipped': 0}, lambda: dict(hashes),
            (PublicRegistryValue(r'HKLM\SOFTWARE\Native Instruments\Fixture', 'ContentDir',
                                 r'C:\Program Files (x86)\Common Files\Native Instruments\Fixture'),),
            BundledRuntime('data/OFFLINE/bag/vcredist_x64.exe', 7, digest(b'runtime')) if runtime else None)
        settings = SimpleNamespace(wine_prefix_directory=Path(root)/'prefixes', installation_directory=Path(root)/'install',
                                   wine_executable='wine', yabridge_directory=None, manage_wine=True, manual_mode=False)
        def progress(stage, completed, total, message):
            if stage == cancel_stage: raise WineCancelled('Fixture cancellation')
        manager = NiApplicationManager(profile, settings, progress=progress)
        calls = []
        def run(argv, **options):
            calls.append((argv, options))
            if argv[1] == 'x':
                source = Path(next(value[2:] for value in argv if value.startswith('-o')))
                for relative, value in payloads.items():
                    path = source/'data'/relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'bad' if source_tamper and relative == rows[0]['source'] else value)
                if profile.runtime:
                    path = source/profile.runtime.path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'runtime')
            elif argv[1] == 'wineboot.exe':
                for architecture in (('system32',) if broken_boot else ('system32', 'syswow64')):
                    path = options['prefix']/'drive_c/windows'/architecture/'kernel32.dll'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'MZ')
            if registration_failure and '/v' in argv and argv[argv.index('/v')+1] == 'ContentDir':
                raise WineError('Public path registration failed')
            return 'wine-11.19' if argv[1] == '--version' else ''
        context = ExitStack()
        context.enter_context(patch.object(manager, 'preflight', return_value=[]))
        context.enter_context(patch.object(manager, '_prepare_display'))
        context.enter_context(patch.object(manager, '_wine', return_value='/fixture/wine'))
        context.enter_context(patch.object(manager, '_run', side_effect=run))
        context.enter_context(patch.object(manager, '_stop_prefix'))
        context.enter_context(patch('ni_application_manager.shutil.which', return_value='/fixture/7z'))
        context.enter_context(patch('ni_application_manager.shutil.disk_usage', return_value=SimpleNamespace(free=10*1024**3)))
        context.enter_context(patch('ni_application_manager._archive_members', return_value=[{'Path': str(n)} for n in range(3)]))
        context.enter_context(patch('ni_application_manager._publish_directory', side_effect=lambda source, target: source.rename(target)))
        return context, manager, archive, rows, hashes, calls

    def test_complete_original_payload_registration_and_receipt_before_installed(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            with context:
                self.assertFalse(manager.installation_status()['installed'])
                result = manager.install(archive)
                self.assertEqual(result.title, 'Fixture')
                self.assertEqual(result.activation, 'unverified')
                self.assertTrue(manager.installation_status()['installed'])
                manager.verify_installation()
                receipt = json.loads((manager.prefix/manager.receipt_name).read_text())
                self.assertEqual(receipt['files'], hashes)
                self.assertEqual(receipt['profile'], 'fixture')
                registry = [argv for argv, options in calls if '/reg:64' in argv]
                self.assertEqual(len(registry), 1)
                self.assertEqual(registry[0][registry[0].index('/v')+1], 'ContentDir')
                self.assertTrue(any('/install' in argv for argv, options in calls))
                self.assertFalse(any(argv[0] == '/fixture/wine' and 'Setup PC.exe' in argv[1] for argv, options in calls))

    def test_optional_runtime_profile_runs_no_prerequisite_installer(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root, runtime=False)
            with context:
                manager.install(archive)
                self.assertFalse(any('/install' in argv for argv, options in calls))
                self.assertTrue(manager.installation_status()['installed'])

    def test_changed_original_source_rejected_before_wine_initialization(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root, source_tamper=True)
            with context, self.assertRaisesRegex(WineError, 'payload fingerprint mismatch'):
                manager.install(archive)
            self.assertFalse(any(argv[1] == 'wineboot.exe' for argv, options in calls))
            self.assertFalse(manager.prefix.exists())

    def test_wrong_zip_digest_never_prepares_display_or_publishes(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            changed = bytearray(archive.read_bytes()); changed[-1] ^= 1; archive.write_bytes(changed)
            with context, patch.object(manager, '_prepare_display', side_effect=AssertionError('must not prepare')), self.assertRaisesRegex(WineError, 'Unsupported installer'):
                manager.install(archive)
            self.assertFalse(manager.prefix_root.exists())

    def test_existing_prefix_preserved_and_arbitrary_prefix_registration_refused(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            manager.prefix.mkdir(parents=True)
            sentinel = manager.prefix/'preserve'; sentinel.write_text('existing')
            with context:
                with self.assertRaisesRegex(WineError, 'already exists'): manager.install(archive)
                with self.assertRaisesRegex(WineError, 'managed application prefix'):
                    manager.register_installation_paths(Path(root)/'foreign')
            self.assertEqual(sentinel.read_text(), 'existing')
            self.assertEqual(calls, [])

    def test_boot_registration_failure_and_cancellation_roll_back_stage(self):
        for options in ({'broken_boot': True}, {'registration_failure': True}, {'cancel_stage': 'publishing'}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as root:
                context, manager, archive, rows, hashes, calls = self.fixture(root, **options)
                with context, self.assertRaises((WineError, OSError)):
                    manager.install(archive)
                self.assertFalse(manager.prefix.exists())
                self.assertEqual(list(manager.prefix_root.iterdir()), [])

    def test_late_completion_callback_cannot_report_published_install_as_failure(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root, cancel_stage='complete')
            with context:
                self.assertEqual(manager.install(archive).status, 'installed')
                self.assertTrue(manager.installation_status()['installed'])

    def test_publication_collision_preserves_the_new_foreign_destination(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            def collision(source, target):
                target.mkdir()
                (target/'foreign').write_text('preserve')
                raise WineError('Publication destination exists')
            with context, patch('ni_application_manager._publish_directory', side_effect=collision):
                with self.assertRaisesRegex(WineError, 'destination exists'): manager.install(archive)
            self.assertEqual((manager.prefix/'foreign').read_text(), 'preserve')
            self.assertEqual(list(manager.prefix_root.iterdir()), [manager.prefix])

    def test_manifest_rejects_escape_adjacent_root_duplicate_and_missing_fingerprint(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            for target in ('Program Files/../outside', 'Program Files/Native Instruments/Fixture-other/file'):
                changed = [dict(row) for row in rows]; changed[0]['target'] = target
                profile = replace(manager.profile, load_plan=lambda: {'files': changed})
                with self.assertRaises(WineError): validate_payload(profile)
            duplicate = [dict(row) for row in rows]; duplicate[1]['target'] = duplicate[0]['target'].upper()
            with self.assertRaises(WineError): validate_payload(replace(manager.profile, load_plan=lambda: {'files': duplicate}))
            with self.assertRaises(WineError): validate_payload(replace(manager.profile, load_hashes=lambda: {}))

    def test_receipt_identity_and_launch_record_do_not_authorize_other_profiles(self):
        with tempfile.TemporaryDirectory() as root:
            context, manager, archive, rows, hashes, calls = self.fixture(root)
            with context:
                manager.install(archive)
                record = manager.installation_status()
                with patch('ni_application_manager.subprocess.Popen', side_effect=AssertionError('no execution')):
                    with self.assertRaises(WineError): manager.launch_record({**record, 'version': '2.0'})
                    with self.assertRaises(WineError): manager.launch_record({**record, 'prefix': '/foreign'})
                    (manager.prefix/'drive_c'/manager.profile.executable_target).write_bytes(b'bad')
                    with self.assertRaisesRegex(WineError, 'executable changed'): manager.launch_record(record)
                receipt_path = manager.prefix/manager.receipt_name
                receipt = json.loads(receipt_path.read_text()); receipt['profile'] = 'other'
                receipt_path.write_text(json.dumps(receipt))
                self.assertFalse(manager.installation_status()['installed'])


if __name__ == '__main__': unittest.main()
