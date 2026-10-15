# Massive 1.7.0 and exact application profiles

`MassiveManager` is a thin exact Massive 1.7.0 descriptor over
`NiApplicationManager`. Kontakt and Maschine retain their existing managers.
The engine requires a fully qualified original installer, complete target plan
and complete fingerprints for every profile. It does not guess other installers
or execute their InstallAware wrappers/MSI custom actions.

## Original source qualification

The launcher downloaded the authorized `Massive_Installer.zip` using its real
product-bound download button. The 209,250,331-byte ZIP matched NI's resolved
Metalink SHA-256:
`764f39a99dfd9e7e02216791523cfd096f7889b968d54463d65756e8991cb663`.
Its sole member is `Massive 1.7.0 Setup PC.exe`, 209,583,728 bytes, SHA-256
`2184549d7a2aef5e41c66935092d85a160ca3e30d75c66f4254871f7d66417bf`.
Native 7-Zip 26.04 extracted 6,752 files and 67 directories.

The matching public installed Massive executable and cached MSI both identify
version 1.7.0. Read-only original MSI tables establish 3,384 unique selected
files, 531,518,498 bytes. All public manifest-listed reference files were hashed,
with no missing files or size/type mismatches. Every original extracted source
file then matched its target's name, size and full SHA-256 fingerprint.

The current authorized archive and cached MSI use different salted source
folders despite identical payload bytes. Qualification binds each original
source to the pinned target manifest by filename, size and full hash. For 3,353
targets, alternative source buckets contain byte-identical originals; the plan
chooses one deterministically. There are no unmatched target files. Runtime
installation uses only this fixed, fingerprinted plan.

Two older local ZIPs are identical Massive 1.5.11 installers. They do not match
the currently resolved authorized 1.7.0 artifact, and this profile rejects them.
No 1.7 metadata is applied to those older installers.

## Original application resources and paths

The profile preserves the original standalone, plug-ins, documentation and
default sound files. It also preserves original bundled resources under these
fixed legacy paths inside the private Wine prefix:

- `Program Files (x86)/Common Files/Native Instruments/Massive`
- `Program Files (x86)/Common Files/Native Instruments/Shared Content/Sounds/Massive`
- `Program Files (x86)/Common Files/Native Instruments/Kore 2/Database Cache/Massive.kdb`

These original factory resources, preset/cache templates and MIDI mappings come
from the verified installer. Separate cataloged libraries, expansions, user
presets and projects are outside this profile. No account, serial, activation
or licensing state is copied from Windows.

Original selected 64-bit MSI registry metadata supplies exactly `InstallDir`,
`InstallVST64Dir` and `ContentDir` under
`HKLM\SOFTWARE\Native Instruments\Massive`. ContentDir points to the original
legacy Massive resource directory above. Those public installation paths are
registered unchanged. Standard MSI service, self-registration, COM, type-library
and assembly tables contain no entries.

The original bundled x64 Visual C++ runtime is 25,234,792 bytes, SHA-256
`ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4`.
It runs unchanged with `/install /quiet /norestart`. No external runtime download,
binary patch or speculative DLL override is included.

## Lifecycle and integration

The engine stages privately, checks the complete source before Wine startup,
initializes a fresh WoW64 prefix, verifies both Wine architectures, runs the
original optional bundled prerequisite, places and rehashes every original file,
registers only the profile's selected public paths and writes a public receipt.
It stops its own staged Wine server before exclusive directory publication.
Cancellation, prerequisite/registration failure and publication collisions roll
back staging while preserving existing or concurrently created destinations.
Late progress receiver failure cannot turn successful publication into a reported
rollback. Optional Mono/Gecko prompts are suppressed only during Wine bootstrap.

`ApplicationProfile`, `InstallerArtifact`, `BundledRuntime` and
`PublicRegistryValue` are frozen metadata records in `ni_application_manager`.
Each profile fixes its allowed target roots, file count/bytes, plan and
fingerprint digests, original installer identity, executable and selected paths.
A profile with no bundled prerequisite may use `runtime=None`.
`NiApplicationManager(profile, settings, progress=None, cancelled=None)` exposes
`install(Path)`, `installation_status()`, `verify_installation()`,
`launch_application()`, `launch_record(record)` and
`register_installation_paths(prefix=None)`. Inventory and verification belong on
workers. Results use the existing `InstallResult.to_dict()` contract.

`MassiveManager(settings, ...)` adds `install_massive_170(Path)` and
`launch_massive()`. Its managed prefix is `settings.wine_prefix_directory/massive`
and its receipt is `.native-access-linux-massive.json`. Installed status requires
the complete pinned receipt and original file types/sizes; verification rehashes
all 3,384 files. Launch rechecks the original executable and only accepts canonical
managed launch records. Activation always remains `unverified`.

Source qualification and focused unit tests have passed. Actual installation,
standalone editor, audio, plug-in hosting, uninstall and activation qualification
remain separate launcher-button tests; process creation alone establishes none
of those outcomes.
