# NI Linux project comparison — 15 October 2026

Read-only repository research. Neither nilinux nor vstenv was installed or executed. Our side was checked against current local 0.9.0 development source; runtime results come from this project's existing verification records and the root agent's observed button tests.

The important finding is that [nilinux](https://github.com/dguedry/nilinux) explicitly redirects development to [vstenv](https://github.com/dguedry/vstenv). Comparing only nilinux misses its maintained successor.

| Area | nilinux / successor | Our Native Access Linux |
| --- | --- | --- |
| Architecture | Python/GTK manager for the original Windows Native Access and NTK inside Wine | Python/Qt independent Linux account, catalog, downloads and launcher; Wine only for Windows products |
| Installation breadth | Generic NI installer execution with MSI trace/FileBag fallback, plus third-party installers | Exact verified product profiles; Kontakt 8.9.0 and Maschine 2.18.4 integrated; other profiles in development |
| Native Linux binaries | Primarily Windows compatibility | Additional Phasis/Reaktor ELF VST2 installation on Arch |
| Launch / sound | Successor documents Kontakt standalone/VST3 and libraries playing in DAWs on Ubuntu, Mint and Fedora; these are maintainer reports | Kontakt standalone opened and a prior demo produced measured audio; Maschine main startup still hangs; broad standalone pass unfinished |
| Activation | Keeps the original NI authorization flow and daemon. A nonempty local JWT is only a status heuristic in inspected nilinux code, not proof of validity | Authorized activation remains unverified; native login/catalog access does not establish product activation |
| GUI | GTK/libadwaita environment, programs, installation and health tools; official Native Access remains the product manager | Direct native account catalog, inline settings/sign-in/progress, product buttons |
| Updates | Original NA self-updates disabled; deliberate supplied installer update and interrupted-install recovery | No general qualified product-update workflow yet |
| Uninstall | Programs Run/Uninstall advertised; exact implementation was not retrieved in this review | Current managed uninstall validates recorded hashes and preserves remaining prefix/user data; root reports actual button install/uninstall observations |
| DAWs | yabridge VST2/VST3/CLAP support, Wine consistency checks | Windows plug-in bridging is not yet qualified |
| Packaging / CI | Flatpak manifest inspected. Documentation describes automated builds, tests and releases; CI job status not independently retrieved | Python wheel/sdist tested; Arch-first runtime, other distributions untested, no comparable observed public CI/release pipeline |
| Maintenance | nilinux says no further releases; successor is vstenv | Active prototype development |

Judgment: their project family is further along as a usable Windows audio compatibility environment, especially DAW bridging and distribution. Ours is further along the distinct goal of an independent native Native Access interface. Ours is not yet more mature overall. Neither source reading nor README claims prove all standalone NI apps work, particularly Maschine.

## Code evidence

- [products.py](https://raw.githubusercontent.com/dguedry/nilinux/main/nilinux/products.py): installer attempt, MSI trace-driven fallback, deployment via MSI tables, interrupted-install handling. The inspected deployment skips missing files and reports their count; its file equality check uses size. Our exact-profile hash verification is stricter for the narrow supported artifacts. Its `licensed` flag checks a nonempty JWT file, not validity.
- [wine.py](https://raw.githubusercontent.com/dguedry/nilinux/main/nilinux/wine.py): hash-pinned portable Wine 11.17 staging WoW64; WINEFSYNC=1; one Wine build for prefix and DAW hosts; explicit host process namespace handling.
- [yabridge.py](https://raw.githubusercontent.com/dguedry/nilinux/main/nilinux/yabridge.py): implementation of bridge installation/discovery/sync, beyond README-only scope.
- [Flatpak manifest](https://raw.githubusercontent.com/dguedry/nilinux/main/flatpak/io.github.dguedry.nilinux.yml): GNOME 50, extraction dependencies and audio/X11 permissions. Retrieved manifest snapshot predates newer README host-namespace/host-filesystem changes, so it must not be represented as current HEAD.
- [vstenv README](https://github.com/dguedry/vstenv#tested): maintainer-reported end-to-end configurations and remaining limitations; GPL-3.0 successor versus MIT nilinux/our project. Preserve licensing when reusing any code; conceptual comparison is independent of code reuse.

## Concrete runtime leads for Maschine — hypotheses only

[NI setup code](https://raw.githubusercontent.com/dguedry/nilinux/main/nilinux/native_access.py) provisions a native Microsoft UCRT from VC2019 and matched VC2022 DLL set with overrides, before product installation. It extracts and starts NI's original NTKDaemon service from Native Access resources. Its setup order is prefix/Wine registration, matching built-ins, fonts, runtime, registry, download location, optional hardware-Vulkan DXVK, bridge and URL handler. Native Access is then extracted and its own fixes/daemon installed. No NI Hardware service requirement was established in inspected code.

[Health checks](https://raw.githubusercontent.com/dguedry/nilinux/main/nilinux/doctor.py) examine which prefix owns NTK ports 7865/5563/5146 and require a PulseAudio/PipeWire socket for standalone sound. These offer controlled comparisons; none proves why our Maschine hangs. Do not copy license tokens or apply Native Access's Electron/PE changes to Maschine. Neither inspected README specifically lists Maschine as runtime-verified.

## Evidence limits

The web reader served repository files with differing cache ages (days to a month), and GitHub tree/commit/CI endpoints were unavailable. A retrieved release page shows v0.1.8 / commit 7bd52f8 released 11 September, but it is an older cached snapshot and is NOT asserted to be the latest release. No reliable current HEAD/date was established. Avoid comparing version numbers or commit/star counts as maturity metrics. Pin and inspect a single revision before adopting implementation details.

## Recommendation: avoid a second compatibility stack

Further inspection of the successor supports a narrower project goal: an independent native NI account/catalog/download experience, using existing compatibility infrastructure wherever practical. A second complete Wine provisioning, installer recovery, plugin bridging and packaging implementation would duplicate substantial existing work. A native GUI alone is not a distinction: vstenv already has a GTK/libadwaita GUI.

[vstenv's CLI](https://raw.githubusercontent.com/dguedry/vstenv/main/vstenv/cli.py) exposes setup, installer dispatch, program launch/removal, bridge synchronization and health checks. Its command handlers call package functions. [Its vendor interface](https://raw.githubusercontent.com/dguedry/vstenv/main/vstenv/vendors/__init__.py) exposes product installation, installed-product enumeration, launch fixes and health checks, with third-party vendor entry points. These are credible integration seams, not evidence of a stable remote API or a drop-in replacement for our backend. The inspected CLI prints human-readable output; reliable UI progress, cancellation and state reconciliation still need an adapter or upstream interface work. The default registry also gives built-in vendor IDs precedence, so a third-party entry point cannot simply replace the built-in NI module with the same ID.

The meaningful distinction is that our account/catalog/download interface runs independently of the Windows Native Access storefront. vstenv's documented NI workflow still launches the original Native Access inside Wine. That distinction is worthwhile only if it produces a demonstrably simpler and reliable installation/authorization workflow. Both approaches still rely on proprietary NI products and their authorization requirements; an open-source launcher does not make Kontakt or Maschine native/open-source products.

Recommended decision gate: compare a pinned vstenv revision in a separate environment using Kontakt and Maschine, including sound, restart, plugin discovery and uninstall; then prove one of our catalog downloads can pass through its installer/runtime path. Prefer contributing reusable integration upstream if viable. Keep our UI work only where it improves the user workflow. If vstenv alone meets the desired experience, use it and stop the duplicate implementation. No claim is made that vstenv fixes our observed Maschine startup hang; its documented Kontakt results remain maintainer reports until independently reproduced.

The current exact-profile engine shares implementation, but each product version still needs individual artifact, installation-plan and payload qualification. Expanding that approach across the entire NI catalog would impose ongoing maintenance. Additional product adapters are held pending this reuse assessment; existing profile files and runtime evidence are preserved.
