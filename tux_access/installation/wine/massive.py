"""Qualified exact original Massive 1.7.0 application profile."""
from tux_access.installation.plans.massive_170 import load_plan, load_hashes, PLAN_SHA256, HASHES_SHA256
from tux_access.installation.wine.application import (ApplicationProfile, BundledRuntime, InstallerArtifact,
                                    NiApplicationManager, PublicRegistryValue)

ZIP_SIZE = 209250331
ZIP_SHA256 = '764f39a99dfd9e7e02216791523cfd096f7889b968d54463d65756e8991cb663'
EXE_TARGET = 'Program Files/Native Instruments/Massive/Massive.exe'
KEY = r'HKLM\SOFTWARE\Native Instruments\Massive'
PROFILE = ApplicationProfile(
    key='massive', title='Massive', version='1.7.0', upid='02cf2683-8802-4ccc-b7c4-78c89f7d3fad',
    artifact=InstallerArtifact(ZIP_SIZE, ZIP_SHA256, 'Massive 1.7.0 Setup PC.exe', 209583728,
                               '2184549d7a2aef5e41c66935092d85a160ca3e30d75c66f4254871f7d66417bf', 6752),
    plan_sha256=PLAN_SHA256, fingerprints_sha256=HASHES_SHA256,
    file_count=3384, payload_bytes=531518498, executable_target=EXE_TARGET,
    allowed_target_roots=(
        'Program Files/Native Instruments/Massive',
        'Program Files/Native Instruments/VSTPlugins 64 bit',
        'Program Files/Common Files/VST3/Massive.vst3',
        'Program Files/Common Files/Avid/Audio/Plug-Ins/Massive.aaxplugin',
        'Program Files (x86)/Common Files/Native Instruments/Massive',
        'Program Files (x86)/Common Files/Native Instruments/Kore 2/Database Cache/Massive.kdb',
        'Program Files (x86)/Common Files/Native Instruments/Shared Content/Sounds/Massive',
    ),
    load_plan=load_plan, load_hashes=load_hashes,
    registry_values=(
        PublicRegistryValue(KEY, 'InstallDir', 'C:\\Program Files\\Native Instruments\\Massive\\'),
        PublicRegistryValue(KEY, 'InstallVST64Dir', 'C:\\Program Files\\Native Instruments\\VSTPlugins 64 bit\\'),
        PublicRegistryValue(KEY, 'ContentDir', 'C:\\Program Files (x86)\\Common Files\\Native Instruments\\Massive'),
    ),
    runtime=BundledRuntime('data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe', 25234792,
                           'ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4'),
)


class MassiveManager(NiApplicationManager):
    def __init__(self, settings, progress=None, cancelled=None):
        super().__init__(PROFILE, settings, progress=progress, cancelled=cancelled)

    def install_massive_170(self, installer_zip):
        return self.install(installer_zip)

    def launch_massive(self):
        return self.launch_application()
