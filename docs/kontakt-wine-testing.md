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

## Remaining verification

The next checks are complete installed resources/registry records, standalone
launch, native-host VST3 discovery, editor behavior, legitimate NI activation,
and MIDI playback with a real instrument. None is inferred from a successful
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
