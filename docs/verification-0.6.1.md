# Catalog actions and physical Arch testing

Version 0.6.1 adds Download and Install buttons to each product row. Download
loads installer metadata in a background worker and filters it to the product.
Native Install accepts only a matching Linux .deb verified by this launcher's
current session. A successful install preserves other account catalog rows.
Windows installers remain downloadable; their installation backend is pending.

All 67 tests passed on the Arch guest, including six product-action workflows.
The desktop was restarted and the visible row buttons inspected. System
authentication chooses a fixed `pkexec /usr/bin/pacman` command when available,
otherwise the existing noninteractive sudo route. Both command selections were
tested with mocks. A live Polkit password dialog on a physical desktop has not
yet been tested.

To test on an x86-64 physical Arch desktop, extract the source distribution and
run these commands inside its directory:

```sh
sudo pacman -S --needed python python-pip firefox xdg-utils carla
python -m venv .venv
.venv/bin/python -m pip install ".[desktop]"
bash tools/prepare_arch_compat.sh
.venv/bin/native-access-linux
```

Sign in, load Account catalog, then Download beside Phasis or Reaktor 6. Select
the Linux installer, wait for a verified download, and click Install in the same
row. Your desktop's Polkit agent may ask for the system password. If it has no
agent, follow the terminal build/install route in [native installation](native-installation.md).
The launcher does not store or request that password.

Open Carla and scan `/usr/lib/vst` for these VST2 plug-ins. These Linux payloads
do not install standalone applications, so there is no Reaktor app-menu entry.
Phasis audio processing passed in the VM. Reaktor instrument playback, editors
and NI activation still require verification. Kontakt's Wine runtime is being
tested separately and is not a working catalog installation in this release.

The VM's earlier AVX boot failure was traced to a CPUID leaf-D bug in its QEMU
WHPX backend. A separate experimental QEMU copy corrected that subleaf branch;
the original executable was preserved. Hardware-accelerated Arch boot and an
actual AVX instruction test then passed with XSAVE size 832 bytes. This VM-only
experiment is not included in the launcher distribution and does not establish
Kontakt compatibility on physical hardware.
