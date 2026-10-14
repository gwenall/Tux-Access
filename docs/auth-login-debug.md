# Embedded NI login investigation — 2026-10-14

The first user-operated Arch sign-in displayed NI's branded "Something went
wrong. Please contact technical support." page before any credential fields.
A VM-only screenshot confirmed that WebEngine rendered the provider page.
The page did not identify the failing request or cause. Guest application
logs contained graphics fallback and UPower messages, with no certificate
failure observed in the inspected interval.

Static comparison with the already decoded installed Native Access 3.26.0
JavaScript found that the embedded login path always requests `prompt=login`.
The relevant calls are at character offsets 384768–386290 in the private
reference file `work/main-readable-candidates.js`; its URL builder is near
372736. Our URL builder supported this option, but `oauth_login.py` omitted
it. The embedded launcher now explicitly supplies `force_login=True`.

Client ID, audience, native callback, PKCE challenge/method, scopes, response
type and `noBackButton` matched the inspected reference builder. Mandatory
OAuth state remains an independent security measure. No evidence established
that special authentication headers or a NativeAccess user-agent were needed.
The reference window uses the default Electron session; our private Qt
profile remains another difference whose effect is unverified.

Both credential-free non-browser authorization probes returned HTTP 403,
with an "Access Denied" HTML page. Those results did not distinguish requests
with and without `prompt=login`, and do not establish the cause of the
different page seen in the embedded browser.

All 37 tests passed on Arch after the request correction. The running launcher
was restarted. A fresh user retry is required to corroborate whether this
correction changes the provider behavior. Successful sign-in and token
exchange are still unverified; the initial page error is not claimed fixed.
