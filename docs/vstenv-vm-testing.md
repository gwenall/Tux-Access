# vstenv comparison test, 15 October 2026

This comparison is in progress, not a runtime qualification of vstenv or our
launcher. It uses the user's existing Arch QEMU guest and installed Flatpak
`io.github.dguedry.vstenv` version 0.1.73, deployment commit
`092693620600b1cd61b2e8b04e2755bc158d78485c46e96debeb997d76c939c5`.
The deployment commit identifies the Flatpak, not a verified Git source revision.

The initial GUI attempt failed with GTK display initialization errors. A launch
with Wayland socket permission, `GDK_BACKEND=wayland`, `GSK_RENDERER=cairo` and
the guest's `WAYLAND_DISPLAY=wayland-1` opens the GUI. The Wayland socket and GTK
renderer settings were added as per-user overrides for this Flatpak.

The temporary reference-session SSH forward on guest port 5146 was stopped
before testing so that it cannot conflict with an NI daemon in vstenv. Our
launcher's current in-memory catalog session and existing product prefixes were
left intact. vstenv uses its own `~/.local/share/vstenv/prefix` and provisions
its pinned Wine 11.17 build, separately from our launcher-managed prefixes.

The Flatpak's host-spawn helper initially had no display variables. A separate
authenticated, TCP-disabled Xwayland display `:10` was started for the test,
and its display environment supplied to the user session's activation services.
The first headless Wine bootstrap was stopped only in vstenv's own prefix; its
host helper and GUI were restarted after correcting the environment.

The minimal guest had PipeWire but no PulseAudio-compatible service or session
manager. `pipewire-pulse` and `wireplumber` were installed and started. WirePlumber
now enumerates the guest ALSA loopback with a default stereo sink and source.
This is useful test infrastructure, not proof of physical audio output or an
explanation of the previously observed Maschine hang.

The GUI has reached its Install tab; a complete health review and product tests
are still pending. No Kontakt or
Maschine launch, sound, activation, plugin bridging or uninstall result from
vstenv is claimed here. See [project comparison](project-comparison.md) for the
recommended reuse assessment and its evidence limits.
