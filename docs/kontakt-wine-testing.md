# Kontakt Wine integration experiment

Kontakt 8 installation and instrument playback are still under test. The
native 0.6 installer supports the observed Linux Phasis/Reaktor packages;
it does not yet provide a supported Kontakt Wine installation workflow.

## Reference artifact and isolated environment

The authorized NI artifact catalog supplied the official Kontakt 8.9.0
Windows installer ZIP, matching the version installed on the reference PC.
This particular download used the existing Windows reference account session.
No account token or Windows activation data was saved or copied into Linux.

- ZIP size: 1,166,054,646 bytes.
- SHA-256: `3c711e00494a369cce1604d9640598999612f08af422a5f39c9bd9163e29728d`.
- ZIP member: `Kontakt 8 8.9.0 Setup PC.exe` (1,166,054,456 bytes).
- Guest runtime: Arch, Wine 11.19, a separate user-owned 64-bit WoW64 prefix.
- A nested authenticated Xwayland display has TCP listening disabled and
  leaves the existing Weston resolution and Applications menu intact.

The NI installer is InstallAware. Its bundled Visual C++ runtime 14.42.34433
completed successfully, but the first two installation attempts stopped making
progress at “Computing space requirements”, before Kontakt payload files were
installed. The second attempt used InstallAware's documented `/l=...` logging.
The extracted source and private installer log were retained for investigation.

The MSI is an InstallAware wrapper with custom actions and runtime directory
properties, rather than an independent conventional payload MSI. A direct
`msiexec /i` without those properties is not a verified replacement for the
installer. Unchanged EXE/VST3 payloads are present in its extracted source;
their presence alone does not establish installation, activation or playback.

## CPU compatibility observed in this VM

Plain `qemu64` with WHPX boots reliably but advertises neither SSE4 nor AVX.
Two AVX configurations failed to boot: hand-added flags and the coherent
`SandyBridge,tsc-deadline=off` model. A retained verbose log from the latter
shows:

```text
CPUID D.0: EAX=7, EBX=576, ECX=832
CPUID D.2: EAX=256, EBX=576
XSAVE consistency problem: size 832 != kernel_size 576
x86/fpu: XSAVE disabled
Failed to execute /init (error -1)
Kernel panic: No working init found
```

The later capability warnings and init failures are also retained.

Using the same Sandy Bridge model with QEMU TCG software emulation completed
boot. A bounded native C probe checked CPUID, XGETBV and executed an actual
AVX instruction:

```text
SSSE3=1 SSE4.1=1 SSE4.2=1 XSAVE=1 OSXSAVE=1 AVX=1
XCR0=0x7
XSAVE current size=832 maximum size=832
PASS: actual AVX instruction executed
```

The launcher service, 2560×1080 scale=1 and Applications menu survived that
boot. TCG is materially slower; this check does not establish usable real-time
audio performance. The installer still stalled with TCG/AVX, both with kernel
NTSync and a separately verified Wine-server synchronization fallback.

A subsequent exact-binary investigation found the WHPX leaf-D branch selected
subleaves 1/2 instead of 0/1 for the hypervisor's dynamic EBX result. A separate
QEMU test copy changed only that branch immediate, with original build SHA-256,
unique instruction context and one-byte difference guards. The original binary
was preserved. Arch then booted successfully with WHPX and the same Sandy Bridge
CPU model; the probe above again passed, including actual AVX execution and
XSAVE size 832 bytes. Display and menu settings remain intact. This establishes
recovery of the VM CPU path, not Kontakt installation or playback. The changed
copy no longer has the original signature coverage and is not shipped here.

## Original payload placement and standalone demo playback

The observed MSI File/Component/Directory tables and selected runtime directory
properties produced a plan for 8,134 unique original files (1,940,318,107 bytes),
with no unresolved entries. The original ZIP digest was rechecked before writing.
Placement into the isolated WoW64 prefix rejected path escapes, symlink ancestry,
duplicate destinations and existing files. Each placed file was independently
SHA-256 compared with its source; a private receipt records those hashes.
No Windows account, license or activation data was copied. MSI custom actions
and its uninstall registration have not been reproduced.

Kontakt 8.9.0 standalone opened its normal Demo/Buy/Activate dialog. Its Run Demo
option and Audio/MIDI settings then opened the main editor. The bundled Piano
Uno instrument loaded, including its resource editor and on-screen keyboard.
An ALSA loopback card supplied the otherwise missing VM audio device. A bounded
in-memory eight-second playback check captured 768,000 S32 samples at 48kHz
stereo while on-screen keys were pressed: normalized peak 0.04581898 and
RMS 0.00205412. These establish finite nonzero standalone demo playback; no
captured audio file was saved. Audio underruns were observed, so this is not
a real-time performance qualification or physical output test.

The initial experiment used a private legacy prefix. Version 0.7 adds an exact
managed adapter for the same original Kontakt 8.9.0 ZIP. A fresh install into
the default `wine-prefixes/kontakt-8` directory initialized WoW64, installed the
bundled original VC runtime, verified every one of the 8,134 payload files,
and published the prefix exclusively. The published executable then opened
Kontakt's main window through the manager's owned Xwayland display. Its process
environment confirmed the new managed prefix and display `:9`; the earlier
legacy experiment used a different prefix and display `:8`.

Installation and licensing remain different states; original NI demo limits
and activation checks remain intact. The launcher prefers the healthy managed
installation, with guarded read-only detection of the earlier legacy installation
as a fallback. It does not duplicate Kontakt or copy activation state.

The current 7-Zip package can list all 8,148 files in the official installer,
including the OFFLINE payload, directly on Linux. This offers a native extraction
path used by the reproducible managed adapter, avoiding the stalled Windows wrapper.
Wine bootstrap disables only the optional Mono/Gecko download prompts; an otherwise
hidden Wine Mono installer had stalled prefix creation on this minimal desktop.
Normal Kontakt execution keeps its ordinary runtime behavior.

## Remaining verification

The next checks are installer/registry integration, native-host VST3 discovery,
reliable GUI embedding, legitimate NI activation, external MIDI routing and
audio performance on physical hardware. None is inferred from a successful
download or extracted executable. NI binaries and artwork are not distributed
with this repository.

The pinned upstream yabridge development build `b580a9f7` is available privately
in the test VM for the later VST3 check; it has not yet established compatibility
with Kontakt or the installed Wine version.

## Primary references

- [Wine architecture options](https://man.archlinux.org/man/wine.1.en).
- [InstallAware logging and setup switches](https://www.installaware.com/mhtml5/desktop/setupcommandlineparameters.htm).
- [Kontakt installation and setup](https://docs.native-instruments.com/ni-tech-manuals/kontakt-manual/en/installation-and-setup).
- [QEMU WHPX CPUID handling](https://github.com/qemu/qemu/blob/master/target/i386/whpx/whpx-all.c).
- [Linux XSAVE consistency validation](https://github.com/torvalds/linux/blob/master/arch/x86/kernel/fpu/xstate.c).
- [Upstream yabridge development builds](https://github.com/robbert-vdh/yabridge#installing-a-development-build).
