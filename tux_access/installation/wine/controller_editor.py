"""Qualified exact original Controller Editor 2.8.2 application profile."""
from tux_access.installation.plans.controller_282 import load_plan, load_hashes, PLAN_SHA256, HASHES_SHA256
from tux_access.installation.wine.application import (ApplicationProfile, BundledRuntime, InstallerArtifact,
                                    NiApplicationManager, PublicRegistryValue)

ZIP_SIZE = 59011192
ZIP_SHA256 = '09f7b4fa0e1e038c2890469deeb00e5ae301b16d59caabe831de3382cdecbc5a'
EXE_TARGET = 'Program Files/Native Instruments/Controller Editor/Controller Editor.exe'
HARDWARE_SERVICE_TARGET = 'Program Files/Common Files/Native Instruments/Hardware/NIHardwareService.exe'
PROFILE = ApplicationProfile(
    key='controller-editor', title='Controller Editor', version='2.8.2',
    upid='f2ce397b-a6f5-4680-90a2-2b567517fa61',
    artifact=InstallerArtifact(ZIP_SIZE, ZIP_SHA256, 'Controller Editor 2.8.2 Setup PC.exe', 59428880,
                               'b0e2036b28d6f32dcee6d18ab2a734cad9d99170166acc84c91fafe4d6f0e336', 320),
    plan_sha256=PLAN_SHA256, fingerprints_sha256=HASHES_SHA256,
    file_count=304, payload_bytes=95031868, executable_target=EXE_TARGET,
    allowed_target_roots=(
        'Program Files/Native Instruments/Controller Editor',
        'Program Files/Common Files/Native Instruments/Controller Editor',
        HARDWARE_SERVICE_TARGET,
    ),
    load_plan=load_plan, load_hashes=load_hashes,
    registry_values=(PublicRegistryValue(r'HKLM\SOFTWARE\Native Instruments\Controller Editor',
                                        'InstallDir', 'C:\\Program Files\\Native Instruments\\Controller Editor\\'),),
    runtime=BundledRuntime('data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe', 25234792,
                           'ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4'),
)


class ControllerEditorManager(NiApplicationManager):
    def __init__(self, settings, progress=None, cancelled=None):
        super().__init__(PROFILE, settings, progress=progress, cancelled=cancelled)

    def install_controller_editor_282(self, installer_zip):
        return self.install(installer_zip)

    def launch_controller_editor(self):
        return self.launch_application()
