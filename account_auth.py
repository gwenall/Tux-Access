"""Independent PKCE preparation. No network I/O without supplied transport.

Public client configuration observed in Native Access 3.26.0. Direct token
exchange passed with a fresh user-operated NI browser login on Arch.
Transient authorization codes, verifiers and tokens are never persisted here.
"""
import base64
import hashlib
import secrets
import re
from urllib.parse import urlencode, urlsplit, parse_qs

AUTH_ORIGIN = 'https://auth.native-instruments.com'
CLIENT_ID = 'GgcQZ2OCSvzqgVL7RSAoErQRNB9S59kh'
AUDIENCE = 'https://api.native-instruments.com'
BROWSER_REDIRECT = 'https://na-cloud.native-instruments.com/en/native-access/auth-handler'
APP_REDIRECT = 'native-access://authorize'


def pkce_challenge(verifier):
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
        raise ValueError('Invalid PKCE verifier')
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')


def new_verifier():
    return secrets.token_urlsafe(32)


def _origin(origin):
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or parsed.hostname != 'auth.native-instruments.com'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Untrusted authentication origin')
    return AUTH_ORIGIN


def _redirect(redirect_uri):
    if redirect_uri not in (BROWSER_REDIRECT, APP_REDIRECT):
        raise ValueError('Unrecognized redirect URI')
    return redirect_uri


def authorize_url(verifier, state, redirect_uri=BROWSER_REDIRECT,
                  client_id=CLIENT_ID, origin=AUTH_ORIGIN, force_login=False):
    """Construct browser URL; caller keeps state and verifier only in memory."""
    if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{22,128}', state):
        raise ValueError('Expected unpredictable URL-safe OAuth state')
    if not isinstance(client_id, str) or not client_id:
        raise ValueError('Missing OAuth client ID')
    parameters = dict(client_id=client_id, audience=AUDIENCE,
                      redirect_uri=_redirect(redirect_uri), code_challenge=pkce_challenge(verifier),
                      code_challenge_method='S256', scope='openid profile offline_access',
                      response_type='code', noBackButton='true', state=state)
    if force_login:
        parameters['prompt'] = 'login'
    return _origin(origin) + '/authorize?' + urlencode(parameters)


def callback_code(callback_url, expected_state, redirect_uri=BROWSER_REDIRECT):
    """Validate exact callback target and state before accepting an auth code."""
    expected = urlsplit(_redirect(redirect_uri))
    actual = urlsplit(callback_url)
    if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path) or actual.fragment:
        raise ValueError('Untrusted authentication callback')
    parameters = parse_qs(actual.query, keep_blank_values=True)
    if 'error' in parameters or 'error_description' in parameters:
        raise ValueError('Authorization was not granted')
    state = parameters.get('state', [])
    if (not isinstance(expected_state, str) or
            not re.fullmatch(r'[A-Za-z0-9_-]{22,128}', expected_state) or
            len(state) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{22,128}', state[0]) or
            not secrets.compare_digest(state[0], expected_state)):
        raise ValueError('OAuth state mismatch')
    codes = parameters.get('code', [])
    if len(codes) != 1 or not codes[0] or len(codes[0]) > 8192:
        raise ValueError('Missing or ambiguous authorization code')
    return codes[0]


def daemon_login_data(code, verifier, redirect_uri=BROWSER_REDIRECT):
    """Observed NTK auth0Login request data; sending it requires explicit caller."""
    pkce_challenge(verifier)
    if not isinstance(code, str) or not code or len(code) > 8192:
        raise ValueError('Invalid authorization code')
    return dict(authCode=code, codeVerifier=verifier, redirectUri=_redirect(redirect_uri))


def exchange_code(code, verifier, transport, redirect_uri=BROWSER_REDIRECT,
                  client_id=CLIENT_ID, origin=AUTH_ORIGIN):
    """OAuth exchange through transport(method,url,headers,body).

    Transport must verify TLS, reject HTTP redirects, avoid sensitive logging,
    bound response size, and return a decoded JSON dictionary. No default HTTP
    transport is supplied here; the native adapter passed a fresh Arch login.
    """
    data = daemon_login_data(code, verifier, redirect_uri)
    if not isinstance(client_id, str) or not client_id:
        raise ValueError('Missing OAuth client ID')
    body = urlencode(dict(grant_type='authorization_code', client_id=client_id,
                          code=data['authCode'], code_verifier=data['codeVerifier'],
                          redirect_uri=data['redirectUri'])).encode('ascii')
    response = transport('POST', _origin(origin) + '/oauth/token',
                         {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}, body)
    if not isinstance(response, dict) or 'error' in response:
        raise RuntimeError('Token exchange failed')
    if not isinstance(response.get('access_token'), str) or not response['access_token']:
        raise RuntimeError('Token exchange returned no access token')
    return response
