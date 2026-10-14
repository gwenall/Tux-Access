# Native VST2 installation on Arch

The first supported payloads are NI's Linux `ni-phasis` 1.2.1 and `ni-reaktor`
6.4.3 Debian packages. They contain VST2 libraries and resources, not standalone
applications or VST3 plug-ins. Download them with this launcher's authenticated,
checksum-verifying downloader. NI binaries are not supplied by this project.

Prepare the required legacy ABIs from the source checkout:

```sh
bash tools/prepare_arch_compat.sh
```

This verifies the archived Arch OpenSSL 1.1 package signature, checks Apache's
Xerces 3.2.5 source digest, and builds Xerces with the GNU iconv transcoder.
It prepares libraries under `~/.local/lib/native-access-linux/compat-legacy`.
The installer validates their real ELF SONAMEs, packages them under
`/usr/lib/native-access-linux/compat-legacy`, and adjusts only the local VST
copies' library search path. The original downloaded .deb remains intact.

In the GUI, choose Install Linux package and select a .deb downloaded in the
same launcher session. This path uses an existing `sudo -n` grant. The development
VM already has that grant. On other machines, use the terminal build route:

```sh
python launcher.py --build-arch-vst ni-phasis_Installer.deb \
  --expected-sha256 SHA256_FROM_VERIFIED_DOWNLOAD \
  --compat-libraries "$HOME/.local/lib/native-access-linux/compat-legacy/lib" \
  --output-dir local-packages
sudo pacman -U local-packages/*.pkg.tar.xz
```

The builder restricts payload paths to the observed plug-ins, resources and NI
registry files. It excludes Debian maintainer scripts, records original and
installed hashes, removes world-writable file permissions, and emits pacman
integrity metadata. Privileged GUI installation uses private runtime staging
and removes temporary package bundles after completion or failure.

Installed payload records include compatibility-library hashes. The desktop
shows Installed with activation unverified, or Installation needs repair when
recorded files are absent or changed. Refresh the account catalog to merge its
records with these local installations.

Verification commands:

```sh
pacman -Qkk native-access-linux-compat native-access-ni-phasis native-access-ni-reaktor
/usr/lib/carla/carla-discovery-native vst2 /usr/lib/vst/Phasis.so
timeout 45s python tools/vst_dsp_probe.py /usr/lib/vst/Phasis.so --expected-id 1315513418
```

Carla is an optional host used for testing: `sudo pacman -S carla`.
Phasis passed finite, nonzero audio processing. Reaktor's instrument and FX
variants passed discovery, but its fresh default instance remained silent;
a real ensemble/preset and instrument playback still need validation.

Both Debian packages declare `Pre-Depends: ni-plugin-info`. That NI helper's
descriptor integration is not implemented. This independent launcher uses
its own installation inventory and generic VST hosting. NI license activation,
editor behavior and other NI hosts remain unverified. Wine/VST3 installation
is not provided by this native installer. Ubuntu/CentOS installation backends
remain future work.

Pacman owns the installed files. Removal is available from a terminal:

```sh
sudo pacman -R native-access-ni-phasis
sudo pacman -R native-access-ni-reaktor
```

Remove the compatibility package only after no installed product needs it.
