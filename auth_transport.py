"""Native OAuth HTTP transport with bounded responses and redacted errors.

The NI token endpoint is evidenced statically; a fresh NI login still needs
end-to-end verification. This implementation uses platform TLS verification.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlencode
from account_auth import AUTH_ORIGIN, CLIENT_ID

class AuthTransportError(RuntimeError):
    pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuthTransportError('Authentication redirect rejected')

class AuthHttpTransport:
    def __init__(self, timeout=20):
        if not isinstance(timeout, (int,float)) or not 0 < timeout <= 60:
            raise ValueError('Timeout must be in (0,60] seconds')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect())

    def __call__(self, method, url, headers, body):
        parsed = urlsplit(url)
        if (method != 'POST' or parsed.scheme != 'https' or
            parsed.hostname != 'auth.native-instruments.com' or
            parsed.port not in (None,443) or parsed.path != '/oauth/token' or
            parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise AuthTransportError('Untrusted authentication endpoint')
        if not isinstance(body,bytes) or len(body) > 32768:
            raise AuthTransportError('Invalid authentication request')
        request=urllib.request.Request(url,method=method,headers=headers,data=body)
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                if response.status != 200:
                    raise AuthTransportError('Authentication request failed')
                if response.headers.get_content_type() != 'application/json':
                    raise AuthTransportError('Unexpected authentication response type')
                payload=response.read(1024*1024+1)
                if len(payload)>1024*1024:
                    raise AuthTransportError('Authentication response exceeded limit')
                result=json.loads(payload.decode('utf-8'))
        except urllib.error.HTTPError as exc:
            raise AuthTransportError(f'Authentication request rejected (HTTP {exc.code})') from None
        except (urllib.error.URLError,OSError,UnicodeDecodeError,ValueError):
            raise AuthTransportError('Could not obtain a valid authentication response') from None
        if not isinstance(result,dict) or 'error' in result:
            raise AuthTransportError('Authentication provider rejected the request')
        return result

def refresh_token(token, transport=None):
    """Candidate standard refresh flow; does not change the Windows daemon."""
    if not isinstance(token,str) or not token or len(token)>16384:
        raise ValueError('Invalid refresh token')
    transport=transport or AuthHttpTransport()
    body=urlencode({'grant_type':'refresh_token','client_id':CLIENT_ID,'refresh_token':token}).encode('ascii')
    response=transport('POST',AUTH_ORIGIN+'/oauth/token',
                       {'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body)
    if not isinstance(response,dict) or not isinstance(response.get('access_token'),str) or not response['access_token'] or 'error' in response:
        raise AuthTransportError('Refresh returned no access token')
    return response
