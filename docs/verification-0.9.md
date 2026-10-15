# Development verification, 15 October 2026

This is an ongoing application test pass. It does not establish that every NI
application works on Linux. Install, Launch and Uninstall observations below
used the visible launcher buttons in the Arch QEMU guest. Shell helpers were
limited to source deployment, unit checks and read-only diagnostics; no CLI
installer call was substituted for the recorded button tests.

## Maschine 2.18.4

The existing managed application reproduced the original splash's
"Initializing audio..." stall after Launch. Its original 793 selected files
had previously passed full SHA-256 verification. Uninstall was selected and
confirmed in the embedded banner: recorded files were removed, other prefix
state retained, and the account row returned to Install. Install then fetched
and verified the exact original NI artifact, initialized a fresh prefix,
installed its bundled runtime and published the files. The fresh application
again showed the same startup stall. A second button-based Uninstall completed;
the application is left uninstalled and its retained directories are displayed
in the launcher status.

This passes the file-install/removal cycle and fails standalone runtime
qualification. A process or splash is not a working application.

Additional bounded diagnostics found no missing original file or ordinary MSI
service/COM table action. The VM's ALSA loopback and explicit Wine ALSA selection
did not resolve the earlier stall. An endpoint probe enumerated three render
and three capture endpoints. A no-Start WASAPI probe passed all twelve default
render/capture, console/multimedia/communications, shared/exclusive combinations
through IAudioClient initialization; no audio was recorded. These results do
not identify the application-specific wait or prove playable audio. A temporary
window-manager comparison also did not resolve it and was removed. Windows-side
unwinding reached NI caller modules but no public NI function symbols.

## Catalog, UI and artwork

The original NTK public product catalog identified sixteen standalone
applications/utilities. Their account-authorized full-products metadata
contains PC installers for all sixteen. The independent account catalog now
expands those known bundle children from that metadata and exposes Applications
without showing separate library/expansion rows. A shared public product identity
merges the M32 Maschine entitlement with the installed Maschine application.
Neither installer availability nor account ownership claims runtime support.

Fourteen original user-supplied PNGs are included with descriptive filenames.
All source/copy hashes match, all fourteen hashes are distinct, and the eight
legacy cache names are migrated for no-repeat selection. The live updated
launcher displayed one of the new singer illustrations after restart.

The complete current source snapshot passed all 196 unit tests in a private
guest directory with `QT_QPA_PLATFORM=offscreen`. This includes the About page,
installer selection/dispatch, exact-profile engines, removal protections and
artwork migration. These checks do not establish product runtime support.
The 0.9.0 source distribution and wheel also built on Arch. A fresh installed
wheel passed imports for the UI, coordinators and every new backend/profile;
all fourteen artwork files and the comparison documentation were present.

## Remaining application tests

Massive 1.7 and Controller Editor 2.8.2 original installers were downloaded and
reported verified through their product-bound Advanced download buttons.
Massive's new exact profile has 3,384 original files matched between the vendor
archive and original reference. Controller Editor's matching public reference
plan has 304 files. Massive is dispatched by the coordinator; Controller Editor's
profile is saved but not enabled in the product dispatcher. Real
Install/Launch/Uninstall and remaining standalone applications are untested.
Additional adapter expansion is held while evaluating reuse of vstenv's
compatibility infrastructure. No success is inferred from
profile creation, archive extraction or unit-test mocks.

Physical audio, controller USB support, DAW integration and legitimate product
activation remain separate unverified capabilities.
