"""Optional in-memory display name for the NI account menu."""
import json
import urllib.error
import urllib.request
from account_api import _NoRedirect, AccountApiError

PROFILE_URL = 'https://auth.native-instruments.com/userinfo'


def profile(token, opener=None):
    if not isinstance(token, str) or not token or len(token) > 32768 or '\r' in token or '\n' in token:
        raise ValueError('Invalid access token')
    request = urllib.request.Request(PROFILE_URL, headers={'Authorization': 'Bearer ' + token,
                                      'Accept': 'application/json'}, method='GET')
    opener = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            if response.status != 200 or response.headers.get_content_type() != 'application/json':
                raise AccountApiError('Account display name is unavailable.')
            payload = response.read(65537)
            if len(payload) > 65536:
                raise AccountApiError('Account profile exceeded the display limit.')
            data = json.loads(payload.decode('utf-8'))
        if not isinstance(data, dict):
            raise AccountApiError('Invalid account profile response.')
        result = {}
        for key in ('name', 'given_name'):
            value = data.get(key)
            if isinstance(value, str) and value.strip() and len(value) <= 200 and not any(ord(c) < 32 for c in value):
                result[key] = value.strip()
        return result
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, UnicodeError, json.JSONDecodeError):
        raise AccountApiError('Account display name is unavailable.') from None
