# Native Access Linux — Python proof of concept 0.9.0 (development)

An independent MIT-licensed launcher targeting Arch Linux first. The proof of
concept stays in Python while the interfaces are established and tested. A
Rust port can follow once the product interfaces are stable. NI software and artwork are
not included or relicensed.

## Install and launch on Arch
The native Wayland desktop was tested in an Arch QEMU VM. See
[Arch VM verification](docs/arch-vm-verification.md) for tested distribution
packages and results.

From a normal terminal:

```sh
sudo pacman -S python python-pip firefox xdg-utils
git clone https://forgejo.my-cloud.me/My-Cloud/native-access.git
cd native-access
python -m venv .venv
.venv/bin/python -m pip install ".[desktop]"
.venv/bin/native-access-linux
```

The native desktop uses Qt through PySide6. Linux sign-in opens your default
browser and returns through NI's registered `native-access` app link. Install
a browser and `xdg-utils`; Firefox is tested in the Arch VM. The launcher
registers a user-local desktop handler when starting sign-in.
Command-line queries and package inspection work without the desktop extra.
Ubuntu and CentOS-family systems can use the same virtual-environment steps
with Python 3.10+ and their distribution's desktop libraries. These distributions
have not yet been tested. Older CentOS releases may lack suitable Qt wheels.

## What to test on Arch
1. Start the desktop and click Sign in. Complete NI's authorization page in
   your browser, then allow it to open Native Access Linux. Leave the launcher's
   main window open. Its inline sign-in banner waits for the browser callback,
   with Cancel and retry controls. It validates the returned state and completes an S256
   PKCE exchange using NI's HTTPS relay redirect. Fresh browser login and
   native token exchange have passed on Arch. Report errors without copying
   codes or tokens.
2. Your account catalog loads automatically after sign-in. Use search or the
   All products, Applications, Ready to install and Installed views. Applications
   includes known bundle applications when the authorized installer catalog
   supplies their metadata, while excluding libraries and expansions. Installed state comes
   from verified local files, rather than ownership in the account catalog.
3. Open the embedded Settings page to choose download and Wine-prefix folders.
   Click Install beside a supported product. The launcher selects its verified
   installer, downloads or verifies a cached copy, and installs it using these
   settings. Progress, cancellation and retry appear in the main window.
4. Automatic Arch installation supports Phasis and Reaktor 6 Linux VST2 packages,
   and exact Kontakt 8.9.0 / Maschine 2.18.4 Windows artifacts through managed Wine prefixes.
   The launcher prepares required system tools through the system authentication
   dialog (Polkit), or an existing noninteractive sudo grant on minimal desktops.
   Native VST2 plug-ins appear in a host such as Carla. Kontakt has a Launch action.
5. Every uninstalled product row has one Install action. Supported products go
   straight through the configured workflow; unsupported products report the
   current limitation inline. Maschine file installation is verified; its main editor/audio startup is still being qualified in the VM.
   Advanced tools remain available for original downloads, package inspection and manual native
   installation. Manual mode exposes controls without disabling explicit Install.
6. Select a qualified managed local installation and use Uninstall in its
   details. Confirm inside the main window. Only recorded application files
   are removed; projects, preferences and other prefix state are retained in
   a dated private directory shown in the footer. Native removal keeps shared
   dependencies. Existing manual/legacy experiments are not removed by this action.

The account initial opens Switch account and Sign out. Settings and About stay
inside the main window. Fourteen user-supplied musical Tux illustrations use
descriptive filenames; one is selected for each app process without immediately
repeating the previous illustration. See [desktop workflow](docs/ui-workflow.md),
[Wine management](docs/wine-management.md) and
[native installation](docs/native-installation.md) for details.

Connect existing session is a reference bridge to a running Windows/macOS NTK
daemon, default tcp://127.0.0.1:5146. It is useful on the reference machine but
is not required for native Linux sign-in. Linux has no local
NI daemon in this project. A localhost SSH tunnel can forward a reference
daemon if desired; the client accepts loopback endpoints only.

## Implemented and verified
* Native Qt desktop catalog, search, readable details and JSON import/export.
* Existing-session bridge; account credentials/tokens stay in process memory.
* Native HTTPS account-catalog and artifact-metadata adapters.
* Protobuf field codec for 132 recovered top-level/nested NTK message definitions.
* Read-only catalog, preferences and active-deployment queries against NTK.
* Authenticated Metalink resolution and streaming verified downloads.
* Download progress/cancellation, private temporary files, existing-file
  protection and cleanup of rejected/cancelled payloads.
* Offline Debian package and ELF dependency inspection.
* Local Arch package conversion, managed native VST2 file installation and
  installed-record integrity checks for Phasis/Reaktor, including private
  legacy library ABIs. Real Qt installer workers passed on Arch.
* Linux system-browser sign-in, private callback delivery and PKCE/state
  validation. Fresh NI authorization and native token exchange pass on Arch;
  token refresh remains unverified.
* Embedded settings, automatic catalog refresh, stable product filters, account
  menu and supported-product installation using saved paths.
* Fresh managed Kontakt 8.9.0 Wine-prefix creation, bundled original VC runtime,
  extraction and verification of all 8,134 original payload files, exclusive
  prefix publication and standalone launch. Optional local Xwayland support is
  managed for minimal Wayland desktops. See [Kontakt testing](docs/kontakt-wine-testing.md).

Windows live validation used the installed Native Access 3.26.0 / NTK 1.32.0:
257 daemon products, 61 account records and 1,586 artifact records. Account and
daemon catalogs are different representations; account records do not establish
installed state. The Qt worker path from existing session through catalog,
artifact metadata and download passed with a real Linux Phasis .deb.
Its 5,891,556-byte payload matched NI's SHA-256 Metalink digest.

The Phasis package contains a 64-bit x86 ELF VST plug-in with VSTPluginMain,
plus resources and NI registry metadata. It needs older libraries including
libssl.so.1.1/libcrypto.so.1.1. Phasis and Reaktor were subsequently installed
and discovered in Carla on Arch. Installed Phasis also passed a numerical
audio-processing test; Reaktor's empty default state remained silent even with
MIDI, so instrument playback is not confirmed. NI activation and custom editors
are unverified. See [0.6 verification](docs/verification-0.6.md). Three
catalog artifacts are labeled linux-x86_64 (Phasis and two Reaktor builds);
this does not establish supported Linux desktop releases or their usability.

## Still required
Token refresh verification; broader product catalog/bundle handling;
expanded native installation, product updates and location handling;
download resume/queue persistence; authorized product activation; expanded Wine
product adapters beyond the exact Kontakt/Maschine builds; and further plug-in-host testing. The exact
Kontakt adapter does not establish support for arbitrary Windows installers.
VST3 bridging, other Linux distributions and frozen desktop packages remain
unverified. The full Native Access replacement is not complete.

The development tree also contains an experimental Massive 1.7 coordinator
profile and a Controller Editor 2.8.2 profile that is not yet enabled. Their
original artifact/payload fingerprints and unit checks pass; their real
Install/Launch/Uninstall cycles remain untested. The current source passes
196 unit tests on Arch; see [development verification](docs/verification-0.9.md).

Further adapter expansion is held while evaluating existing compatibility
infrastructure. [vstenv](https://github.com/dguedry/vstenv), the successor to
nilinux, already covers substantial Wine, installer and plugin-bridging work.
Our distinct aim is the independent native NI account/catalog workflow. See the
[comparison and reuse recommendation](docs/project-comparison.md) and
[ongoing VM comparison test](docs/vstenv-vm-testing.md). No vstenv implementation
has been incorporated into this MIT-licensed source tree.

## CLI and tests
From the source directory:

```sh
python launcher.py --probe
python launcher.py --probe --export catalog.json
python launcher.py --inspect preferences
python launcher.py --inspect deployments
python launcher.py --inspect catalog
python launcher.py --inspect-package package.deb --expected-sha256 HASH
python -m unittest discover -s tests -v
```

Core tests do not contact NI. GUI tests use Qt's offscreen platform and mocks.
The field inventory can be regenerated with tools/build_schema.py and the
recovered inventory in docs/ntk-interface-inventory.json. The schema is specific
to the inspected version; untested operations are not claimed functional.

## Architecture
qt_launcher.py orchestrates native widgets and background operations.
account_auth.py / oauth_login.py / oauth_browser.py / oauth_callback.py /
auth_transport.py handle transient login and the private browser callback.
arch_package.py prepares local Arch packages and verifies installed NI payloads
and compatibility libraries. NI binaries are provided by each user's download.
account_api.py and download_catalog.py provide the native HTTP metadata path.
app_settings.py persists paths and preferences; install_coordinator.py selects
verified workflows. wine_manager.py owns the tested Kontakt prefix lifecycle;
wine_display.py supplies an owned local Xwayland display where required.
download_manager.py resolves Metalinks and downloads verified payloads without
forwarding bearer tokens to the CDN. package_inspection.py reads Debian/ELF
metadata. ntk_protocol.py and schema_codec.py support the reference bridge.
Evidence and runtime limitations are recorded under docs/.

The left sidebar uses eight user-supplied Tux music illustrations. One is selected at startup and stays fixed for that session. See [sidebar artwork](docs/sidebar-art.md).
