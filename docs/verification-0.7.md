# 0.7 verification

The Python launcher was tested on the existing x86-64 Arch VM with Python
3.14.8, PySide6 6.12, Wine 11.19 and native 7-Zip 26.04. The display and
Applications menu were retained. Ubuntu, EL/CentOS-family installations and
frozen distributable desktop packages remain future qualification targets.

## Managed Kontakt

A fresh default managed prefix was created from the original authorized
Kontakt 8.9.0 installer ZIP. Its exact size and SHA-256 were checked, the
bundled original VC runtime was installed, and all 8,134 original payload
files passed independent digest verification. The prefix was published
exclusively without replacing the earlier experimental prefix.

The published Kontakt standalone executable opened through the manager's
private authenticated Xwayland display. The process environment confirmed
`wine-prefixes/kontakt-8` and display `:9`. The legacy experiment used a
different prefix and display `:8`. Original demo and activation behavior
remains intact. This new-prefix launch does not imply NI activation or
DAW/VST3 compatibility.

The earlier legacy experiment loaded Piano Uno and passed a bounded in-memory
audio check through an ALSA loopback device. Audio underruns were observed;
physical output and real-time performance have not been qualified.

## Desktop

Account catalog refresh is automatic after sign-in or reference-session
connection. Optional account-name lookup stays in memory. Switch account asks
the provider for a fresh login; cancellation retains the current session.
Sign out clears account state and keeps local installations/settings.

Settings is embedded in the main window. Supported Install selects, downloads
and verifies an authorized installer using saved paths. Unsupported products
open product-bound Install options with original installer download choices
and an explicit support limitation. Maschine installation is not implemented.
Manual mode exposes advanced controls without disabling supported Install.

Local inventory prefers a healthy managed Kontakt record and recognizes the
earlier legacy prefix through a pinned receipt and full file hashes. Kontakt
appears under Installed and has Launch. Phasis and Reaktor remain native
installed VST2 records. Filtering preserves identity and clears hidden details.

Offscreen tests exercise worker threading, progress/cancellation boundaries,
retry, settings persistence, automatic catalog loading, filtering, account
clearing, enabled product options, error redaction, checksum requirements,
exclusive prefix publication and owned display cleanup. Separate rendered
fixtures use the VM's actual local installation records to inspect narrow-window
button containment and embedded Settings. These fixtures do not log in to NI.

## Limits

The Wine adapter supports the exact verified Kontakt 8.9.0 artifact only.
Other Windows installers, content/library installation, update/uninstall,
NI activation, token refresh, VST3 bridging and physical hardware audio remain
unverified or unimplemented. Native Arch packages use fixed system plug-in
paths; the content-folder setting is reserved for future library installers.
NI binaries, account data and artwork are not included in launcher packages.
