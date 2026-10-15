# Tuxaccess 0.9.2 — rename and documentation

The former Native Access Linux prototype is now branded Tuxaccess. The main
window, sidebar, embedded About page, browser callback display name, diagnostic
messages, Python distribution and primary command use the new name. The legacy
command and existing internal paths remain compatible. The NI callback scheme
and OAuth client configuration have not been changed or represented as an
independent client registration.

About and README describe the independent, unofficial Linux compatibility goal,
identify third-party ownership and retain product licensing/activation limits.
The name and notices are not a legal-clearance claim.

The user removed a visually duplicate Tux illustration. The configured and
packaged pool now contains thirteen images; legacy cache-name translation is
retained. Asset packaging includes the actual remaining PNG files.

## Verification

- All 208 existing unit tests passed on Arch, using Qt's offscreen platform.
- A wheel and source distribution built using the renamed package metadata.
- The installed wheel reported `tuxaccess` version 0.9.2 and supplied both
  `tuxaccess` and the legacy `native-access-linux` command.
- Installed assets resolved outside the source directory: thirteen Tux images,
  desktop launcher, and embedded About page with the updated ownership notice.
- The README screenshot was captured from the installed Qt application on Arch,
  using the VM's actual four verified local installation records. It is not a
  synthetic catalog. The account was not connected in that capture; activation
  remains unverified. The screenshot contains no account identifiers or tokens.

These checks validate the rename and packaging. They do not extend product
compatibility or establish successful activation, audio or DAW bridging.
