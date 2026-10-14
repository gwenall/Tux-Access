# Native installation verification — 2026-10-14

The fresh Arch NI session downloaded both Linux packages through the actual
GUI picker. NI Metalink size and SHA-256 verification completed:

| Package | Bytes | SHA-256 |
| --- | ---: | --- |
| Phasis | 5,891,556 | `c5efd89b72bd3d8c506c6bd6a25d751e7d8609f1467fd23a30fefb33300b40da` |
| Reaktor 6.4.3 | 19,822,456 | `df7a0b5af2031a301db45785ee5873eec5b032362a5c511613d25b7747208482` |

Native local Arch packages installed Phasis, Reaktor's instrument and FX
libraries, presets/resources and NI registry files. Compatibility dependencies
were obtained from a signature-verified Arch OpenSSL 1.1 archive and a
digest-verified Apache Xerces 3.2.5 build. Normal loader resolution succeeds
without setting LD_LIBRARY_PATH or changing system libraries.

Pacman reported zero altered files: three compatibility-library files,
71 Phasis package files and 596 Reaktor package files. Independent installation
records also checked SHA-256 for payloads and compatibility libraries.

| Plug-in | VST2 ID | Host discovery and processing smoke | Numerical audio test |
| --- | ---: | --- | --- |
| Phasis | 1315513418 | Passed; stereo effect, 16 parameters | Passed; finite nonzero output |
| Reaktor 6 | 1315525174 | Passed; 2 audio inputs, 16 outputs, 1000 parameters, synth flag | Default state silent, including MIDI note 64 |
| Reaktor 6 FX | 1314010730 | Passed; 16 inputs/outputs, 1000 parameters | Default state silent |

Carla discovery processing checks were enabled. Its bounded test opens the
plug-in, processes a silent block and closes it. The independent Phasis DSP
test processed 300 blocks of 512 frames at 44.1 kHz with 100 warmup blocks.
Installed-copy input RMS was 0.141419, output RMS 0.104152, output peak 0.222287,
and uncompensated output-minus-input RMS 0.155668. Modulation means these
measurements are observations, not fixed expected values or sound-quality scores.

Reaktor MIDI note-on and note-off were delivered through the VST2 event API.
No loaded ensemble, successful instrument playback or activation was established.
Silence is recorded as silence, not a passing sound test.

All 60 unit tests passed. The real Qt installer worker installed both verified
packages and showed the two local records in the native Wayland GUI. Its file
chooser was supplied deterministically with the already verified local paths;
package conversion, sudo/pacman installation and integrity checks were real.
Private staging rejection, compatibility corruption and temporary-bundle
cleanup have regression coverage. The runtime staging was empty afterward.

NI's `ni-plugin-info` integration, activation, custom editors, standalone NI
applications, Windows compatibility and VST3 remain unverified or unimplemented.
The downloadable NI binaries stay on the user's machine and are not committed
to this independent source repository.
