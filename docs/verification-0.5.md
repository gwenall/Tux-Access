# Verification of 0.5.0 — 2026-10-14

The Arch Wayland launcher completed a fresh user-operated NI sign-in in
Firefox 157.0.1. NI's existing HTTPS relay returned to the user-local
`native-access` desktop handler, which delivered the callback to the waiting
launcher through its private Unix socket. State validation, S256 PKCE and
native HTTPS token exchange completed.

The fresh session loaded 61 account products and 1,586 artifact records,
including three Linux entries. Guest loopback port 5146 had no listener;
the Windows reference-session bridge was disconnected. Credentials were
entered only by the user on NI's page. Account tokens remain in launcher memory.

All 54 tests passed on Arch. These include callback ownership/mode checks,
bounded/replay-resistant delivery, incorrect/Unicode state rejection, expiry,
cancellation and mocked redemption with the original HTTPS redirect.
The actual desktop app-link dispatch passed with a local dummy URI.

The source distribution and Python wheel built on Arch. The installed wheel
imported its desktop modules, delivered a private callback through its CLI,
and included README.md as package data.

The earlier embedded login failed with `net::ERR_HTTP2_PROTOCOL_ERROR`;
an HTTP/1.1 fallback hung. The temporary embedded debugging observer and
protocol override were removed before browser-login verification.

Refresh, installation, activation and product runtime support remain pending.
The existing verified Phasis download and read-only package inspection are
documented separately; they are not a claim that the plug-in runs on Arch.
