# Native Access Linux — Python proof of concept 0.4

An independent MIT-licensed launcher targeting Arch Linux first. The proof of
concept stays in Python while the interfaces are established and tested. A
Rust port follows the working proof of concept. NI software and artwork are
not included or relicensed.

## Install and launch on Arch
The native Wayland desktop was tested in an Arch QEMU VM. See
[Arch VM verification](docs/arch-vm-verification.md) for tested distribution
packages and results.

From a normal terminal:

```sh
sudo pacman -S python python-pip
git clone https://forgejo.my-cloud.me/My-Cloud/native-access.git
cd native-access
python -m venv .venv
.venv/bin/python -m pip install ".[desktop]"
.venv/bin/native-access-linux
```

The native desktop uses Qt through PySide6, including WebEngine for sign-in.
Command-line queries and package inspection work without the desktop extra.
Ubuntu and CentOS-family systems can use the same virtual-environment steps
with Python 3.10+ and their distribution's desktop libraries. These distributions
have not yet been tested. Older CentOS releases may lack suitable Qt wheels.

## What to test on Arch
1. Start the desktop and click Sign in. The embedded browser opens NI's own
   authorization page, catches the registered native redirect, validates state
   and prepares an S256 PKCE code exchange. A fresh NI login remains unverified;
   please report any error without copying codes or tokens.
2. After sign-in, load Account catalog, then Artifact metadata.
3. Open Download artifact, filter by product/platform, choose the exact version
   and a destination folder. The backend resolves a Metalink and verifies the
   payload size and SHA-256 before publishing the completed file.
4. Inspect a downloaded .deb with Inspect package. This reads metadata and ELF
   dependencies without installing the package or running its scripts.

Connect existing session is a reference bridge to a running Windows/macOS NTK
daemon, default tcp://127.0.0.1:5146. It is useful on the reference machine but
is not required for the planned native account backend. Linux has no local
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
* Native embedded sign-in UI, PKCE/callback validation, token/refresh transport
  preparation. Fresh service authorization and refresh remain unverified.

Windows live validation used the installed Native Access 3.26.0 / NTK 1.32.0:
257 daemon products, 61 account records and 1,586 artifact records. Account and
daemon catalogs are different representations; account records do not establish
installed state. The Qt worker path from existing session through catalog,
artifact metadata and download passed with a real Linux Phasis .deb.
Its 5,891,556-byte payload matched NI's SHA-256 Metalink digest.

The Phasis package contains a 64-bit x86 ELF VST plug-in with VSTPluginMain,
plus resources and NI registry metadata. It needs older libraries including
libssl.so.1.1/libcrypto.so.1.1. It was inspected, not installed or loaded. Three
catalog artifacts are labeled linux-x86_64 (Phasis and two Reaktor builds);
this does not establish supported Linux desktop releases or their usability.

## Still required
Fresh account authorization and callback verification on Arch; expanded product
catalog/bundle handling; native install/update/uninstall and location handling;
download resume/queue persistence; authorized product activation; product runtime
and plug-in-host testing. Windows-only products may later use an optional Wine
adapter. The full Native Access replacement is not complete.

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
account_auth.py / oauth_login.py / auth_transport.py handle transient login.
account_api.py and download_catalog.py provide the native HTTP metadata path.
download_manager.py resolves Metalinks and downloads verified payloads without
forwarding bearer tokens to the CDN. package_inspection.py reads Debian/ELF
metadata. ntk_protocol.py and schema_codec.py support the reference bridge.
Evidence and runtime limitations are recorded under docs/.
