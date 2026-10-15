# Controller Editor 2.8.2 managed application profile

`ControllerEditorManager` is a thin exact profile over the shared
`NiApplicationManager`. It installs only the original application, bundled
templates/documentation and original hardware-service executable from its
authorized installer into `settings.wine_prefix_directory/controller-editor`.
It does not establish hardware-service registration, USB/MIDI access, controller
functionality, editor startup or activation merely by placing those files.

## Source qualification

The launcher downloaded `Controller_Editor_Installer.zip` using its real
product-bound download button. Its authorized Metalink size is 59,011,192 bytes
and SHA-256 is
`09f7b4fa0e1e038c2890469deeb00e5ae301b16d59caabe831de3382cdecbc5a`.
The local UI download independently matched both. UPID is
`f2ce397b-a6f5-4680-90a2-2b567517fa61`, version `2.8.2`, platform `pc`.

The sole ZIP member is `Controller Editor 2.8.2 Setup PC.exe`, 59,428,880 bytes,
SHA-256 `b0e2036b28d6f32dcee6d18ab2a734cad9d99170166acc84c91fafe4d6f0e336`.
Native 7-Zip 26.04 listed and extracted 320 files and 29 directories.
The matching original cached MSI public tables establish 304 unique selected
files, 95,031,868 bytes, with no unresolved or skipped rows.

All 304 public installed-reference files were fingerprinted read-only. Every
authorized original source file matched the pinned target's filename, size and
full SHA-256. Two source groups have byte-identical alternatives; source binding
selects an equivalent original deterministically. No Windows binaries, projects,
user templates, account or licensing state are copied into the Linux prefix.

The original standalone fingerprint is
`0f4326542fdb3211ed39acb973907c82b76b12c45e4e27af9559f19d5f1952d4`.
The bundled `NIHardwareService.exe` fingerprint is
`88f90c4b378f547508b09f190b4bcb30a35cbc5f5d16a7a0d533267a2c1956d9`.
Its placement target is the exact original
`Program Files/Common Files/Native Instruments/Hardware/NIHardwareService.exe`;
the profile does not allow arbitrary neighboring hardware files.

## Runtime and original installation metadata

The verified original x64 Visual C++ prerequisite is 25,234,792 bytes, SHA-256
`ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4`.
It runs unchanged with `/install /quiet /norestart`. The installer also bundles
an x86 redistributable; this selected x64 application profile does not run it.

Original selected 64-bit public MSI registry metadata supplies only `InstallDir`
under `HKLM\SOFTWARE\Native Instruments\Controller Editor`, with value
`C:\Program Files\Native Instruments\Controller Editor\`.
The profile writes only that original path. No content path or audio setting is
invented, and no serial, entitlement or activation key is accessed.

Original MSI ServiceInstall, ServiceControl, SelfReg, Class, ProgId, TypeLib and
assembly tables are empty. Its ten custom-action names do not identify a
hardware/service action. This is limited metadata evidence: it does not prove
that the vendor's InstallAware bootstrap performs no service setup. The adapter
does not run or reproduce opaque bootstrap/custom actions or infer a service
installation command from the executable's presence. Hardware support remains
unqualified pending separate evidence.

## API and current validation

`ControllerEditorManager(settings, progress=None, cancelled=None)` exposes
`install_controller_editor_282(Path)`, `launch_controller_editor()`,
`installation_status()`, `verify_installation()` and guarded `launch_record()`.
`ZIP_SIZE`, `ZIP_SHA256` and frozen `PROFILE` are exported for exact installer
selection. The receipt is `.native-access-linux-controller-editor.json`.
The shared engine provides private staging, complete verification, bounded
bootstrap/cancellation, unchanged original prerequisite handling, selected path
registration and exclusive publication. Activation is always `unverified`.

Source qualification and focused tests have passed. Actual Install, Launch and
Uninstall verification must use the launcher buttons. No CLI product install or
launch was performed during profile qualification.
