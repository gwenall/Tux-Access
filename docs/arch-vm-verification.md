# Arch VM verification

Verified on 2026-10-14 in an x86-64 QEMU development VM. Initial checks used
2 CPUs, 3 GiB RAM and software emulation. Subsequent browser-login checks used
the user's upgraded VM with 6 CPUs, 8 GiB RAM and WHPX acceleration. The desktop
uses Weston 15 with its pixman renderer and Qt's native Wayland platform.

Installed packages: Python 3.14.8, PySide6 6.12.0, pyzmq 27.2.0,
qt6-wayland 6.12.0, qt6-webengine 6.11.2, and DejaVu fonts. Qt WebEngine's
HTML/JavaScript smoke check passed with its sandbox enabled and a private
profile. Hardware graphics acceleration was not required.

## Checks that passed

- All 54 unit tests, including asynchronous Qt workers, private browser callback
  delivery, state validation and a mocked HTTPS-relay exchange, passed on Arch.
- The actual OS app-link dispatch through the registered desktop handler and
  private callback socket passed using a local dummy URI.
- Firefox 157.0.1 rendered NI's authorization form after clicking Sign in.
- A user-operated fresh Firefox login returned through NI's relay and the
  private callback handler. Native token exchange, 61 account products and
  1,586 artifact records loaded with the Windows session bridge disconnected.
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
sudo pacman -Syu --needed python pyside6 python-pyzmq qt6-wayland firefox xdg-utils ttf-dejavu
cd native-access-linux
QT_QPA_PLATFORM=wayland python launcher.py
```

This uses Arch's installed Python libraries. For a pip environment, use the
virtual-environment instructions in the project README.

## Remaining checks

Fresh NI authorization now passes on Arch; token refresh is still unverified.
The launcher has not installed or activated a product, and the downloaded plug-in has not been
loaded into a Linux plug-in host. Its legacy OpenSSL dependencies still need
evaluation. The full Native Access replacement remains incomplete.
