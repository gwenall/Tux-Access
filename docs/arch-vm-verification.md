# Arch VM verification

Verified on 2026-10-14 in an x86-64 QEMU development VM with 2 CPUs,
3 GiB RAM, and software emulation. The desktop uses Weston 15 with its
pixman renderer and Qt's native Wayland platform.

Installed packages: Python 3.14.8, PySide6 6.12.0, pyzmq 27.2.0,
qt6-wayland 6.12.0, qt6-webengine 6.11.2, and DejaVu fonts. Qt WebEngine's
HTML/JavaScript smoke check passed with its sandbox enabled and a private
profile. Hardware graphics acceleration was not required.

## Checks that passed

- All 37 unit tests, including the asynchronous Qt workers, passed on Arch.
- The source distribution and Python wheel built on Arch. The wheel installed
  in a virtual environment using Arch's system dependencies; its installed
  CLI reached the reference daemon, desktop modules imported, and README.md
  was present in the installed package data.
- The native Wayland launcher rendered product search and product details.
- A loopback SSH reverse tunnel connected the Arch client to the existing
  Windows NTK daemon. This is a reference-session bridge, not a Linux daemon.
- The existing authorized session retrieved 257 reference-daemon products,
  61 account records, and 1,586 artifact records, including 3 Linux artifacts.
- The Linux Qt worker downloaded the Phasis Linux Debian package. Its
  5,891,556-byte payload matched the size and SHA-256 in NI's Metalink.
- Offline package inspection verified its integrity and x86-64 ELF payload.
- The private WebEngine profile rendered local HTML and executed JavaScript.
- The WebDAV shared source volume passed host-to-guest and guest-to-host
  write checks. Build environments and caches remain on the guest disk.

## Run with Arch packages

```sh
sudo pacman -Syu --needed python pyside6 python-pyzmq qt6-wayland qt6-webengine ttf-dejavu
cd native-access-linux
QT_QPA_PLATFORM=wayland python launcher.py
```

This uses Arch's installed Python libraries. For a pip environment, use the
virtual-environment instructions in the project README.

## Remaining checks

Fresh NI authorization and refresh have not yet been confirmed. The verified
live flow used the reference machine's existing NI session. The launcher has
not installed or activated a product, and the downloaded plug-in has not been
loaded into a Linux plug-in host. Its legacy OpenSSL dependencies still need
evaluation. The full Native Access replacement remains incomplete.
