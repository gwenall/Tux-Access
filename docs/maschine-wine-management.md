# Maschine 2.18.4 managed installation

The Maschine adapter is restricted to the exact authorized Windows Maschine
2.18.4 installer. It installs the original application and its original bundled
static resources into `settings.wine_prefix_directory/maschine-2`. It does not
provide generic NI Windows installer support, Factory Library installation,
controller drivers, VST bridge qualification or activation.

## Artifact and original payload evidence

The account catalog identifies this installer as UPID
`fccc863c-324f-4d79-af7e-b38c1f7488fe`, title `Maschine 2.18.4`, platform `pc`,
hardware platform `any`, version `2.18.4`, file type `installer`, filename
`Maschine_2_Installer.zip`. Its authorized Metalink size is 332,547,451 bytes
and SHA-256 is
`7ed619e713405d14b5097b40a785a5c2081b54ffd393f66b8e4628020d722798`.
`pc` is the observed NI Windows platform value; treating only `win*` strings as
Windows would reject this real artifact.

The ZIP contains exactly `Maschine 2 2.18.4 Setup PC.exe`, 332,925,224 bytes,
SHA-256 `acaef2e6278bc5b19eef19010d05bcbe7c988460102d6445b77dd442cfb74375`.
Native 7-Zip 26.04 listed and extracted its 819 files and 166 directories.
These are observed qualification baselines; older extractors have not been
qualified and are not claimed incapable of decoding the archive.

Read-only public Windows installation metadata establishes the standalone at
`C:\Program Files\Native Instruments\Maschine 2\Maschine 2.exe`, file version
`2.18.4`, product version `2.18.4 (x64)`, 104,337,632 bytes, SHA-256
`29cbc4c6f085f1d0d8ac8ff6302d39a988085adf3e0c455360c369f536923216`.
The original VST3 has version `2.18.4`, size 104,418,016 bytes and SHA-256
`df6db2004f49d6e5a565dbc041a7c03b130671b57d9e982c3de7a794363ec75f`.

The cached MSI descriptor supplied 1,572 File rows, 1,992 components and 628
directories. Only public installation path properties and boolean component
selection flags were read. The strict planner resolved 793 unique files,
454,585,919 bytes, with zero unresolved or skipped entries. All selected targets
are original Program Files payload paths. The plan's SHA-256 is
`9c3bdec563489a113baddf7cfaee6a77db21818aa5fe1eb47be7a6f3116b0f20`.

All 793 public installed-reference payload files were fingerprinted read-only.
The original ZIP was then independently rehashed in Linux, extracted natively,
and all 793 original source hashes matched those fingerprints. No Windows
binaries, account, serial, activation or licensing files were copied. The
packaged plan module contains only paths, sizes and static file fingerprints;
the original NI binaries remain in the user's original authorized installer.

The original bundled x64 Microsoft Visual C++ prerequisite is
`data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe`, 25,234,792 bytes, SHA-256
`ce6593a1520591e7dea2b93fd03116e3fc3b3821a0525322b0a430faa6b3c0b4`.
It is run unchanged with `/install /quiet /norestart`; no external runtime
download or copying of Windows system libraries is performed.

## Lifecycle and status

`MaschineManager` uses the qualified Wine lifecycle and private authenticated
display helper from the Kontakt backend. It verifies the ZIP, sole setup member,
native archive inventory, every original selected payload fingerprint and the
bundled prerequisite before placement. A fresh staged WoW64 prefix initializes
with optional Mono/Gecko prompts suppressed only during `wineboot.exe --init`.
Both 64-bit and 32-bit Wine kernel32 files must exist before proceeding.
Normal NI application launches retain default CLR/HTML loading behavior.

The first cold Maschine prefix initialization reached Wine's normal configuration
update window but exceeded the original 120-second bound; its staged prefix was
discarded safely. The retained bootstrap log contained only the timeout message,
with no additional cause established. Maschine now allows one bounded
300-second initialization, reports elapsed preparation every ten seconds without
a fabricated percentage, and keeps cancellation polling responsive. The Kontakt
timeout is unchanged. No CPU, compositor, device or global Wine setting is
changed to accommodate this retry.

Every placed file is independently hash-checked against the original fingerprint
manifest. Only then is an informational receipt written and the prefix published
using exclusive Linux directory publication. Existing prefixes are preserved;
cancellation and failure discard the staged prefix. Installer spawning or exit
zero alone never produces an installed result. The InstallAware wrapper and MSI
custom actions are not run or reproduced.

Original MSI metadata selects two public 64-bit registry values under
`HKLM\SOFTWARE\Native Instruments\Maschine 2`: `InstallDir` points to
`C:\Program Files\Native Instruments\Maschine 2\` and `InstallVST64Dir` points
to `C:\Program Files\Native Instruments\VSTPlugins 64 bit\`.
`register_installation_paths(prefix=None)` writes exactly these two `REG_SZ`
values using Wine `reg add /reg:64` after payload verification and before
publication. The default call can also maintain an already verified managed
installation after its application session is stopped. Arbitrary prefixes are
refused. The unselected `ContentDir` row is omitted; no account, serial, licensing
or activation keys are accessed. These path entries are normal installer
metadata, and no causal link to the observed audio startup delay is established.

`installation_status()` requires the complete pinned receipt and all original
file types/sizes. `verify_installation()` additionally rehashes all 793 installed
files. `launch_maschine()` checks the standalone's original hash and uses the
selected private prefix/display. `launch_record(record)` accepts only matching
canonical managed Maschine metadata and paths, preventing arbitrary imported
prefix/executable execution. These operations always report activation as
`unverified`; the original NI licensing checks are retained.

The actual fresh-prefix retry completed Wine initialization in roughly eighty
seconds, ran the original bundled Visual C++ runtime, placed and independently
verified all 793 files, and published the managed `maschine-2` prefix. A separate
`verify_installation()` pass rehashed all 793 installed files successfully.
`launch_maschine()` then started the original application process from that
published prefix. Capturing the application's own X11 window showed the original
Maschine 2.18.4 splash at "Initializing audio...". The VM had no ALSA soundcards
at that observation; the main application window and audio startup remain
unqualified. Process creation and a splash do not establish factory content
playback, hardware control, physical real-time audio, VST hosting or legitimate
activation.

Subsequent qualification restored the VM's existing ALSA loopback device, selected
Wine's ALSA driver, registered the two original installation paths and restarted
only the product prefix. The splash persisted. A public API-only counter compiled
with the existing Wine compiler reported three WinMM render and three capture
devices, and three active MMDevice render and capture endpoints. COM creation,
enumeration, counts and default endpoint lookup all returned success; the probe
exited zero. This demonstrates endpoint visibility in that prefix without
establishing the cause of incomplete Maschine startup.

The splash was the only viewable application window; the other windows were
small unmapped notification or IME helpers. Raising and focusing the splash did
not change it. A bounded debugger inspection of public Wine function names
showed the main thread waiting for GUI messages and the audio workers waiting
for events. No application data, arguments or account/licensing state was read,
and the debugger detached normally. No graphics override or additional installer
action is justified by these observations alone.

## Integration

Import `MaschineManager` from `maschine_manager`. Its constructor accepts shared
settings and optional `progress(stage, completed, total, message)` and
`cancelled() -> bool` callbacks. Run installation and inventory on workers.
`install_maschine_2184(installer_zip)` returns the shared `InstallResult` with
`.to_dict()`; status, verification and record-based launch follow the same
desktop contract. `ZIP_SIZE` and `ZIP_SHA256` are exported for exact artifact
selection. Ship `maschine_manager` and `maschine_2184_plan` as Python modules.

Eleven focused unit checks cover original manifest coverage, path and fingerprint
rejection, preservation of existing prefixes, artifact mismatch before Wine
startup, full synthetic publication, refusal of incomplete initialization despite
exit zero, cancellation rollback, exact public path registration, registration
failure rollback, and rejection of arbitrary prefixes and launch records.
