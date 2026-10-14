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
was restarted. Subsequent observations are recorded below; the correction
alone did not establish successful sign-in or token exchange.

## Subsequent user retry

The user subsequently reached the credential form but received a generic
login-attempt error after submission. This establishes that the form rendered;
it does not establish the cause of the subsequent failure or successful account
authorization.

A metadata-only observer was prepared with privacy tests. Its first 15-minute
window expired before the user's attempt and captured no authentication
request. Read-only inspection of the still-open page's resource timing returned
two `/usernamepassword/login` requests with `responseStatus` equal to 0, while
other resources had 200 or 201 statuses. Zero does not identify a server HTTP
status and is insufficient to distinguish a transport or browser-policy error
from another failure.
The [Resource Timing specification](https://www.w3.org/TR/resource-timing/)
also defines zero for opaque filtered responses, so it must not be reported as
a server rejection code.

The observer was extended to two hours and additionally recorded fixed browser
network error codes and CORS indicators, never raw console text. Credentials,
cookies, request bodies and response bodies are excluded from recorded data.

## Captured login transport failure

A subsequent user-operated attempt was captured while the observer was
attached. The POST XHR to `/usernamepassword/login` failed with
`net::ERR_HTTP2_PROTOCOL_ERROR`. Both the network failure event and browser
error indicator reported this code. No HTTP response status, CORS error or
explicit browser blocking reason was recorded for that failed POST. This
identifies a transport failure in the observed attempt; it does not establish
whether the supplied credentials would have been accepted.

The VM's launcher environment temporarily requested an HTTP/1.1 fallback through
`QTWEBENGINE_CHROMIUM_FLAGS="--disable-http2 --disable-quic"`, alongside its
temporary loopback-only debugging setting. Chromium's
[network switch definitions](https://chromium.googlesource.com/chromium/src/+/HEAD/components/network_session_configurator/common/network_switch_list.h)
define these protocol switches, and
[Qt's debugging documentation](https://doc.qt.io/qt-6/qtwebengine-debugging.html)
documents passing Chromium switches through this environment variable.
TLS certificate validation, browser sandboxing and OAuth state validation
remain enabled. The observer additionally records a fixed protocol label.
The observer confirmed HTTP/1.1 on other successful NI requests. The subsequent
credential POST remained pending and the user reported a hang. No successful
login response was observed. This fallback was not made a project-wide default.

## System-browser route

The installed Native Access 3.26.0 also implements browser login using
`https://na-cloud.native-instruments.com/en/native-access/auth-handler`.
NI's [official release notes](https://community.native-instruments.com/discussion/4823/official-update-status-native-access-current-version-3-26-0)
describe the browser-login feature. Read-only inspection of NI's public relay
module established that its default `native-access://authorize` target preserves
all query parameters except `redirect_target`, including OAuth state.

Linux sign-in now uses the system browser and this existing relay. An independent
implementation registers a user-local desktop handler and forwards callbacks
through a private Unix datagram socket to the waiting launcher. The launcher
requires the exact native target, matching state and S256 PKCE verifier. Token
redemption uses the original HTTPS redirect, not the final native relay target.
NI's JavaScript and application binaries are not included in the distribution.

All 54 tests passed on Arch, including callback privacy, mismatched/Unicode state,
expiry, cancellation and mocked token exchange. A local dummy URI also passed
the actual `xdg-open` → desktop handler → CLI → private socket chain. Weston's
generic `xdg-open` parser required safe Exec paths to remain unquoted; paths
requiring quoting retain the standard desktop-entry escaping.

Firefox 157.0.1 was installed in the VM, and the real Sign in action rendered
NI's credential form there. The embedded network observer was stopped and its
temporary remote-debugging and HTTP/1.1 settings removed. A fresh user-operated
browser login subsequently succeeded. The user completed NI's form and returned
to the launcher, which loaded 61 account products and 1,586 artifact records,
including three Linux artifacts. No listener existed on guest port 5146, so
the reference-session bridge was unavailable during this verification. This
confirms fresh browser authorization, relay callback, native token exchange and
direct account API access on Arch. Refresh remains unverified.
