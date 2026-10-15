from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_settings import default_settings
from download_catalog import Artifact
from download_manager import DownloadSpec, DownloadCancelled
from install_coordinator import can_install, install_product, installed_catalog, select_artifact, InstallError
from maschine_manager import MaschineManager


def artifact(title='Phasis', platform='linux-x86_64', name='Phasis.deb', version='1.2.1', size=7):
    return Artifact('same-id', title, version, platform, 'x64', size, name, 'installer', '/reference')


class InstallCoordinatorTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('maschine_manager.MaschineManager')
        self.maschine = patcher.start()
        self.addCleanup(patcher.stop)
        self.maschine.return_value.installation_status.return_value = {'status': 'not installed'}
        patcher = patch('massive_manager.MassiveManager')
        self.massive = patcher.start()
        self.addCleanup(patcher.stop)
        self.massive.return_value.installation_status.return_value = {'status': 'not installed'}

    def test_massive_selects_only_the_exact_qualified_pc_installer(self):
        from massive_manager import ZIP_SIZE
        product = {'title': 'Massive', 'upid': 'same-id'}
        known = artifact('Massive 1.7.0', 'pc', 'Massive_Installer.zip', '1.7.0', ZIP_SIZE)
        self.assertEqual(select_artifact(product, [known], default_settings()), (known, 'wine'))
        for wrong in (replace(known, version='1.6.0'), replace(known, platform='mac'),
                      replace(known, filesize=ZIP_SIZE - 1)):
            with self.assertRaises(InstallError):
                select_artifact(product, [wrong], default_settings())
        self.assertFalse(can_install(product, replace(default_settings(), manage_wine=False)))

    def test_maschine_profile_accepts_exact_pc_build_and_rejects_version_or_payload_change(self):
        from maschine_manager import ZIP_SIZE
        product = {'title': 'Maschine 2', 'upid': 'same-id'}
        known = artifact('Maschine 2.18.4', 'pc', 'Maschine_2_Installer.zip', '2.18.4', ZIP_SIZE)
        self.assertEqual(select_artifact(product, [known], default_settings()), (known, 'wine'))
        for changed in (replace(known, version='2.18.5'), replace(known, filesize=ZIP_SIZE - 1),
                        replace(known, target_file='Unrelated.zip'), replace(known, platform='mac')):
            with self.assertRaises(InstallError):
                select_artifact(product, [changed], default_settings())

    def test_maschine_metalink_digest_change_is_rejected_before_download_or_install(self):
        from maschine_manager import ZIP_SIZE
        known = artifact('Maschine 2.18.4', 'pc', 'Maschine_2_Installer.zip', '2.18.4', ZIP_SIZE)
        self.maschine.return_value.preflight.return_value = []
        spec = DownloadSpec(known.target_file, ZIP_SIZE, '0' * 64, ())
        with patch('install_coordinator.resolve_artifact', return_value=spec), \
             patch('install_coordinator.download') as download:
            with self.assertRaises(InstallError):
                install_product({'title': 'Maschine 2', 'upid': 'same-id'}, 'mock-session', default_settings(), [known])
            download.assert_not_called()
            self.maschine.return_value.install_maschine_2184.assert_not_called()

    def test_inventory_prefers_managed_kontakt_without_duplicate_legacy_row(self):
        managed = {'title': 'Kontakt 8', 'installed': True, 'status': 'installed',
                   'executable': '/managed/Kontakt.exe', 'managed': True}
        with patch('arch_package.installed_products', return_value=[]), \
             patch('wine_manager.WineManager') as backend:
            backend.return_value.installation_status.return_value = managed
            records = installed_catalog(default_settings())
            backend.return_value.detect_legacy_installation.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['binaryPath'], '/managed/Kontakt.exe')
        self.assertTrue(records[0]['managed'])

    def test_inventory_uses_verified_legacy_when_managed_prefix_is_absent(self):
        legacy = {'title': 'Kontakt 8', 'installed': True, 'status': 'installed',
                  'executable': '/legacy/Kontakt.exe', 'managed': False}
        with patch('arch_package.installed_products', return_value=[]), \
             patch('wine_manager.WineManager') as backend:
            backend.return_value.installation_status.return_value = {'status': 'not installed'}
            backend.return_value.detect_legacy_installation.return_value = legacy
            records = installed_catalog(default_settings())
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]['managed'])
        self.assertEqual(records[0]['status'], 'Installed · activation unverified')

    def test_selection_does_not_install_windows_as_native_or_unrelated_product(self):
        product = {'title': 'Phasis', 'upid': 'same-id'}
        native = artifact()
        records = [artifact(platform='win', name='setup.exe'), native,
                   replace(native, upid='other', title='Other', version='99.0')]
        self.assertEqual(select_artifact(product, records, default_settings()), (native, 'native'))
        with self.assertRaises(InstallError): select_artifact(product, records[:1], default_settings())
        self.assertTrue(can_install(product, replace(default_settings(), manual_mode=True)))

    def test_one_click_revalidates_cached_file_from_current_ni_spec_then_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b'fixture'
            digest = hashlib.sha256(payload).hexdigest()
            installer = root / 'Phasis.deb'
            installer.write_bytes(payload)
            settings = replace(default_settings(), download_directory=root)
            spec = DownloadSpec(installer.name, len(payload), digest, ('https://artifacts-cdn.native-instruments.com/private',))
            stages = []
            with patch('install_coordinator.resolve_artifact', return_value=spec), \
                 patch('install_coordinator.download') as downloader, \
                 patch('install_coordinator._prepare_native'), \
                 patch('arch_package.install_verified_vst', return_value={'title': 'Phasis', 'version': '1.2.1'}) as install:
                result = install_product({'title': 'Phasis'}, 'mock-transient-token', settings, [artifact()],
                                         progress=lambda *args: stages.append(args[0]))
            downloader.assert_not_called()
            install.assert_called_once_with(installer, digest)
            self.assertEqual(result['activation'], 'unverified')
            self.assertIn('verify', stages)
            self.assertIn('native_install', stages)
            self.assertNotIn('private', str(result))

    def test_cached_mismatch_is_preserved_and_never_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / 'Phasis.deb'
            installer.write_bytes(b'changed')
            spec = DownloadSpec(installer.name, 7, hashlib.sha256(b'fixture').hexdigest(), ())
            with patch('install_coordinator.resolve_artifact', return_value=spec), \
                 patch('arch_package.install_verified_vst') as install:
                with self.assertRaises(InstallError):
                    install_product({'title': 'Phasis'}, 'mock-session', replace(default_settings(), download_directory=root), [artifact()])
                install.assert_not_called()
            self.assertEqual(installer.read_bytes(), b'changed')

    def test_cancellation_before_network_or_mutation(self):
        with patch('install_coordinator.available_artifacts') as metadata:
            with self.assertRaises(DownloadCancelled):
                install_product({'title': 'Phasis'}, 'mock-session', default_settings(), cancelled=lambda: True)
            metadata.assert_not_called()

    def test_exact_kontakt_build_only_and_wine_disable_prevents_automatic_install(self):
        from wine_manager import ZIP_SIZE
        product = {'title': 'Kontakt 8'}
        known = artifact('Kontakt 8', 'win', 'Kontakt_8_Installer.zip', '8.9.0', ZIP_SIZE)
        self.assertEqual(select_artifact(product, [known], default_settings()), (known, 'wine'))
        pc = replace(known, platform='pc')
        self.assertEqual(select_artifact(product, [pc], default_settings()), (pc, 'wine'))
        with self.assertRaises(InstallError): select_artifact(product, [replace(known, version='9.0')], default_settings())
        self.assertFalse(can_install(product, replace(default_settings(), manage_wine=False)))


if __name__ == '__main__': unittest.main()
