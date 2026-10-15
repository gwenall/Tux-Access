# Managed Wine installation

Native Access Linux has an independent managed Wine backend for **one exact
installer: Kontakt 8.9.0 for Windows**. It does not imply support for other NI
Windows products or versions. The account catalog and download verifier supply
the official installer; this project distributes placement metadata, not NI
binaries, instruments, artwork, activation data or Microsoft runtime binaries.

The ordinary Install action can call `WineManager.install_kontakt_890()` after
download verification. Its default prefix is
`settings.wine_prefix_directory/kontakt-8`. Settings provide the Wine executable,
prefix parent, optional yabridge directory and managed-installation toggle.
Advanced settings do not change the original Windows layout inside the prefix.
The separate content directory is reserved for later library installation;
bundled Kontakt content stays in the observed original locations.

## Verified artifact and lifecycle

The accepted ZIP is exactly 1,166,054,646 bytes with SHA-256
`3c711e00494a369cce1604d9640598999612f08af422a5f39c9bd9163e29728d`.
Its sole member is `Kontakt 8 8.9.0 Setup PC.exe`, 1,166,054,456 bytes.
Other artifacts are rejected before a managed prefix is created.

The backend checks x86-64 Linux, CPU AVX advertisement, Wine and native 7-Zip
versions, the matching Wine server and available disk space. Wine 11.19 and
native 7-Zip 26.04 are the validated baselines. Older versions are blocked by
this prototype's conservative qualification gate; this does not establish that
they cannot run or extract this product. Later version numbers are identified
as unqualified. Dependencies are selected from installed system packages or the
user's explicit settings. The backend performs no sudo operation or arbitrary
dependency download. Missing Arch dependencies have actionable diagnostics.

A private staging directory holds a reverified snapshot of the ZIP and the
native extracted payload. Before extraction, archive inventory paths, link
types, encryption, count and aggregate size are checked. After extraction,
every emitted member is checked for unexpected links and types. The exact
placement metadata represents 8,134 files totaling 1,940,318,107 bytes, with no
unresolved paths. Its source digest is pinned independently of the installer.

The fresh prefix uses Wine's tested `WINEARCH=wow64` configuration, runs
`wineboot.exe --init`, selects Windows 10 and runs the original bundled Microsoft
Visual C++ runtime with `/install /quiet /norestart`. This prerequisite is
extracted only from the accepted original installer at
`data/OFFLINE/mFileBagIDE.dll/bag/vcredist_x64.exe`: 25,640,112 bytes, SHA-256
`1821577409c35b2b9505ac833e246376cc68a8262972100444010b57226f0940`.
No external prerequisite download is needed. Wine menu generation is disabled
with the controlled `winemenubuilder.exe=d` override; this launcher manages its
own desktop entries.

During fresh `wineboot` initialization only, `mscoree,mshtml=` suppresses Wine's
optional Mono and Gecko bootstrap prompts for this native C++ Kontakt prefix.
Normal NI application launches and the bundled Visual C++ installer retain
Wine's ordinary CLR and HTML DLL loading behavior. This avoids an unattended
first-boot prompt without changing NI binaries or licensing checks.

Original payload files are placed exclusively in their observed Program Files
and ProgramData targets. Source and destination hashes are compared. Traversal,
duplicate destinations, foreign-owned staging directories, symlink ancestry and
overwrites are rejected. A receipt records public product metadata and file
hashes. It contains no account, serial, entitlement or activation state.
After Wine shuts down, Linux `renameat2(RENAME_NOREPLACE)` publishes the complete
prefix. An existing prefix is always preserved, including an empty directory.
Cancellation or failure before publication discards the staged installation.

Only failed fresh `wineboot` initialization retains a bounded private diagnostic
log under the prefix parent's `.diagnostics` directory. This directory is mode
0700 and logs are mode 0600. NI application, account and login output is not
captured by that diagnostic path. Hash-verified copy-on-write cloning is used
when available to avoid duplicate ZIP and large payload allocations; streaming
remains the fallback.

This is original payload placement with the original prerequisite. It does not
reproduce InstallAware/MSI custom actions, uninstall registration or entitlement
registration. The normal NI Demo/Buy/Activate checks remain intact. The original
Wine installer wrapper stalled at Computing space requirements in the private
experiment, so the backend uses native extraction rather than that wrapper.

## Installed state and launch

`installation_status()` accepts an installation only when its pinned receipt
matches the complete expected manifest and all files still have their expected
types and sizes. The public status includes `installed: bool` and a `status`
string of `installed`, `not installed` or `needs repair`. It always reports
`activation: unverified`. `verify_installation()` additionally rehashes every
installed file. File presence does not establish legitimate activation.

`launch_kontakt()` uses the selected Wine executable, the managed prefix and
the original standalone executable. It requires a graphical Linux session.
Inherited Wine prefix, loader and DLL overrides are excluded so an unrelated
Wine session does not silently change this managed installation.

On a normal X11 or Xwayland desktop, the existing `DISPLAY` and `XAUTHORITY` are
preserved. On a Wayland-only session, installation and launch prepare a private
authenticated nested Xwayland automatically. It uses a user-owned private
runtime directory, locally generated authority, TCP disabled and a bounded X11
authentication handshake before any Wine initialization. Its 1280×800 decorated
rootful window uses shared memory and software rendering, allowing a minimal
Wayland compositor without a separate X11 window manager. It does not restart
Weston or change the desktop's resolution, scaling or menu.

Reuse requires the recorded process's PID, kernel start time, exact executable
arguments and successful private-cookie authentication to match. Existing X11
sockets and lock files are preserved. Failed startup stops only the child from
the current call; a PID read from saved state is never signaled. Authority
cookies are not placed in command arguments, logs, receipts or UI output. A
missing Xwayland package or graphical session fails with an actionable message.

The private reference experiment established normal standalone Demo mode and
finite nonzero Piano Uno playback. The automated fresh-prefix path separately
completed installation and opened Kontakt's Welcome GUI from its published
prefix. Unit tests establish safety and lifecycle contracts; neither those
checks nor a visible GUI establishes new-prefix audio playback, physical
real-time performance or legitimate activation.

The first automated fresh-prefix guest run extracted the exact installer but
timed out during Wine initialization. Staging was discarded and the existing
private experimental prefix was preserved. Investigation of both the normal
device path and an isolated diagnostic path found the optional Wine Mono
installer awaiting input behind the existing Kontakt window. Waiting threads
did not establish an NTSync or kernel defect. A separate clean-prefix probe with
initialization-only Mono/Gecko suppression then completed successfully and
created `syswow64/kernel32.dll`, using normal host devices and NTSync. The backend
now uses that proven initialization environment. No kernel/device workaround is
implemented. The full fresh managed default-prefix installation then completed
and verified all 8,134 original payload hashes before publication.
`WineManager(default_settings()).launch_kontakt()` then opened the actual Kontakt
Welcome GUI from the published prefix on its private authenticated Xwayland
display `:9`; the existing experimental application on `:8` remained intact.
This verifies the fresh managed installation, prefix relocation and automatic
graphical launch. VST3 bridging, physical real-time performance and legitimate
NI activation remain unverified.

The known earlier experiment can be recognized without migration. Read-only
legacy detection checks only `settings.installation_directory/wine-kontakt-8-wow64`
and the original private cached payload-placement receipt. Its pinned receipt
binds the complete original manifest; all 8,134 files are hash-checked on a
worker. A successful record reports `managed: false`, its actual prefix and
executable, and `activation: unverified`. No receipt, installation, account or
licensing file is changed by detection. `launch_record()` revalidates one of the
known managed or legacy records before launch and rejects arbitrary imported
prefix/executable paths. The application can show one Kontakt row by preferring
the verified managed installation when available, otherwise the verified legacy
installation.

## yabridge and integration interface

The optional yabridge directory is inspected directly for `yabridgectl`,
`yabridge-host.exe` and `libyabridge-vst3.so`. Diagnostics invoke that exact ctl
and identify that exact host path. They never infer DAW scanning, embedding or
playback from a version string. This backend does not yet configure wrappers;
standalone installation can complete without yabridge. The private development
build `b580a9f7` requires its directory ahead of `/usr/bin` when used so a stable
host is not selected accidentally. Real bridge qualification is a separate
check.

The constructor is `WineManager(settings, progress=None, cancelled=None)`.
Callbacks are UI neutral: `progress(stage, completed, total, message)` and
`cancelled() -> bool`. Installation and diagnostics belong on the application's
worker thread. A zero total means a stage without numeric progress. Successful
installation returns `InstallResult` with title, version, status, activation,
backend, prefix, executable, receipt, managed flag and source; `.to_dict()`
supplies a mapping.

The meaningful unit checks cover complete metadata, traversal and duplicate
rejection, source/destination integrity, preservation of existing prefixes,
rollback on cancellation and initialization failure, exclusive Linux publication,
symlink ancestry, receipt-based installed state, dependency selection and
inherited Wine environment isolation. Display tests cover normal desktop
preservation, authenticated reuse, collision avoidance, private permissions,
stale foreign PID preservation and timeout cleanup. Linux-only tests must run
on Linux to exercise ownership, sockets and publication semantics.
